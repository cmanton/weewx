#!/usr/bin/perl
# $Id$
# Copyright 2013 Matthew Wall
#
# register/update a weewx station via GET or POST request
#
# This CGI script takes requests from weewx stations and registers them into
# a database.
#
# The station_url is used to uniquely identify a station.
#
# If the station has never been seen before, a new record is added.  If the
# station has been seen, then a field is updated with the timestamp of the
# request.
#
# Data are saved to a database.  The database contains a single table.
#
# If the database does not exist, one will be created with an empty table.
#
# FIXME: should we have a field for first_seen?
# FIXME: add checks to prevent update too frequently

use strict;
use POSIX;

my $version = '$Id$';

my $basedir = '/home/content/t/o/m/tomkeffer';

# use this when testing so we avoid the real databases
#my $TEST = '-test';
my $TEST = q();

# location of the station database
my $db = "$basedir/weereg/stations${TEST}.sdb";

# location of the history database
my $histdb = "$basedir/weereg/history${TEST}.sdb";

# location of the html generator
my $genhtmlapp = "$basedir/html/register/mkstations.pl";

# location of the log archiver
my $arclogapp = "$basedir/html/register/archivelog.pl";

# location of the count app
my $savecntapp = "$basedir/html/register/savecounts.pl";

# location of the log file
my $logfile = "$basedir/html/register/register.log";

# format of the date as returned in the html footers
my $DATE_FORMAT = "%Y.%m.%d %H:%M:%S UTC";

# how often can clients update, in seconds
my $max_frequency = 60;

# maximum number of unique URLs registered from any given IP address
my $max_urls = 10;

# parameters that we recognize
my @params = qw(station_url description latitude longitude station_type station_model weewx_info python_info platform_info);

my $RMETHOD = $ENV{'REQUEST_METHOD'};
if($RMETHOD eq 'GET' || $RMETHOD eq 'POST') {
    my($qs,%rqpairs) = &getrequest;
    if($rqpairs{action} eq 'chkenv') {
        &checkenv();
    } elsif($rqpairs{action} eq 'genhtml') {
        &runcmd('generate html', $genhtmlapp);
    } elsif($rqpairs{action} eq 'arclog') {
        &runcmd('archive log', $arclogapp);
    } elsif($rqpairs{action} eq 'getcounts') {
        &runcmd('save counts', $savecntapp);
    } elsif($rqpairs{action} eq 'history') {
        &history(%rqpairs);
    } elsif($rqpairs{action} eq 'summary') {
        &summary(%rqpairs);
    } else {
        &handleregistration(%rqpairs);
    }
} else {
    &writereply('Bad Request', 'FAIL', "Unsupported request method '$RMETHOD'.");
}

exit 0;



# figure out the environment in which we are running
sub checkenv {
    my $title = 'checkenv';
    my $tstr = &getformatteddate();
    &writecontenttype();
    &writeheader($title);
    print STDOUT "<p><strong>$title</strong></p>\n";

    # perl
    my $output = `perl -V`;
    print STDOUT "<pre>\n";
    print STDOUT "$output\n";
    print STDOUT "</pre>\n";

    # web server environment
    print STDOUT "<pre>\n";
    for my $k (keys %ENV) {
        print STDOUT "$k = $ENV{$k}\n";
    }
    print STDOUT "</pre>\n";

    # file systems
    my $df = `df -k`;
    print STDOUT "<pre>\n";
    print STDOUT "$df\n";
    print STDOUT "</pre>\n";

    # databases
    print STDOUT "<pre>\n";
    my $rval = eval "{ require DBI; }"; ## no critic (ProhibitStringyEval)
    if(!$rval) {
        print STDOUT "DBI is not installed\n";
    } else {
        my @drivers = DBI->available_drivers();
        my $dstr = "DBI drivers:";
        foreach my $d (@drivers) {
            $dstr .= " $d";
        }
        print STDOUT "$dstr\n";
    }
    print STDOUT "</pre>\n";

    &writefooter($tstr);
}

sub runcmd {
    my($title, $cmd) = @_;
    my $output = q();

    if(! -f "$cmd") {
        $output = "$cmd does not exist";
    } elsif (! -x "$cmd") {
        $output = "$cmd is not executable";
    } else {
        $output = `$cmd 2>&1`;
    }

    my $tstr = &getformatteddate();
    &writecontenttype();
    &writeheader($title);
    print STDOUT "<p><strong>$title</strong></p>\n";

    print STDOUT "<pre>\n";
    print STDOUT "$cmd\n";
    print STDOUT "</pre>\n";

    print STDOUT "<pre>\n";
    print STDOUT "$output\n";
    print STDOUT "</pre>\n";

    &writefooter($tstr);    
}

sub handleregistration {
    my(%rqpairs) = @_;

    my ($status,$msg,$rec) = registerstation(%rqpairs);
    if($status eq 'OK') {
        &writereply('Registration Complete', 'OK', $msg, $rec, $rqpairs{debug});
        &updatestations();
    } else {
        &writereply('Registration Failed', 'FAIL', $msg, $rec, $rqpairs{debug});
    }
}

# update the stations web page then update the counts database
sub updatestations() {
    system("$genhtmlapp >> $logfile 2>&1 &");
    system("$savecntapp >> $logfile 2>&1 &");
#    `$genhtmlapp >> $logfile 2>&1`;
#    `$savecntapp >> $logfile 2>&1`;
}

# if this is a new station, add an entry to the database.  if an entry already
# exists, update the last_seen timestamp.
sub registerstation {
    my(%rqpairs) = @_;

    my %rec;
    foreach my $param (@params) {
        $rec{$param} = $rqpairs{$param};
    }
    $rec{last_seen} = time;
    $rec{last_addr} = $ENV{'REMOTE_ADDR'};
    $rec{user_agent} = $ENV{HTTP_USER_AGENT};

    my @msgs;
    if($rec{station_url} =~ /example.com/) {
        push @msgs, 'example.com is not a real URL';
    }
    if($rec{station_url} =~ /weewx.com/) {
        push @msgs, 'weewx.com does not host any weather stations';
    }
    if($rec{station_url} =~ /register.cgi/) {
        push @msgs, 'station_url should be the URL to your weather station';
    }
    if($rec{station_url} !~ /^https?:\/\/\S+\.\S+/) {
        push @msgs, 'station_url is not a proper URL';
    }
    if($rec{station_url} =~ /'/) {
        push @msgs, 'station_url cannot contain single quotes';
    }
    if($rec{station_type} eq q() || $rec{station_type} !~ /\S/) {
        push @msgs, 'station_type must be specified';
    } elsif($rec{station_type} =~ /'/) {
        push @msgs, 'station_type cannot contain single quotes';
    }
    if($rec{latitude} eq q()) {
        push @msgs, 'latitude must be specified';
    } elsif($rec{latitude} =~ /[^0-9.-]+/) {
        push @msgs, 'latitude must be decimal notation, for example 54.234 or -23.5';
    } elsif($rec{latitude} < -90 || $rec{latitude} > 90) {
        push @msgs, 'latitude must be between -90 and 90, inclusive';
    }
    if($rec{longitude} eq q()) {
        push @msgs, 'longitude must be specified';
    } elsif($rec{longitude} =~ /[^0-9.-]+/) {
        push @msgs, 'longitude must be decimal notation, for example 7.15 or -78.535';
    } elsif($rec{longitude} < -180 || $rec{longitude} > 180) {
        push @msgs, 'longitude must be between -180 and 180, inclusive';
    }
    for my $k ('description','station_model','weewx_info','python_info','platform_info') {
        if($rec{$k} =~ /'/) {
            $rec{$k} =~ s/'//g;
        }
    }
# accept only weewx user agent.  this will reject anything before weewx 2.6
#    if($rec{user_agent} !~ /weewx\//) {
#        push @msgs, 'unsupported registration protocol';
#    }
    if($#msgs >= 0) {
        my $msg = q();
        foreach my $m (@msgs) {
            $msg .= '; ' if $msg ne q();
            $msg .= $m;
        }
        return ('FAIL', $msg, \%rec);
    }

    my $rval = eval "{ require DBI; }"; ## no critic (ProhibitStringyEval)
    if(!$rval) {
        my $msg = 'bad server configuration: DBI is not installed';
        return ('FAIL', $msg, \%rec);
    }
    my $havesqlite = 0;
    my @drivers = DBI->available_drivers();
    foreach my $d (@drivers) {
        $havesqlite = 1 if $d =~ /^sqlite/i;
    }
    if(!$havesqlite) {
        my $msg = 'bad server configuration: DBI::SQLite is not installed';
        return ('FAIL', $msg, \%rec);
    }

    my $dbexists = -f $db;
    my $dbh = DBI->connect("dbi:SQLite:$db", q(), q(), { RaiseError => 0 });
    if (!$dbh) {
        my $msg = 'connection to database failed: ' . $DBI::errstr;
        return ('FAIL', $msg, \%rec);
    }

    my $rc = 0;
    if(! $dbexists) {
        $rc = $dbh->do('create table stations(station_url varchar2(255) not NULL, description varchar2(255), latitude number, longitude number, station_type varchar2(64), station_model varchar2(64), weewx_info varchar2(64), python_info varchar2(64), platform_info varchar2(64), last_addr varchar2(16), last_seen int)');
        if(!$rc) {
            my $msg = 'create table failed: ' . $DBI::errstr;
            $dbh->disconnect();
            return ('FAIL', $msg, \%rec);
        }
        $rc = $dbh->do('create unique index index_stations on stations(station_url asc, latitude asc, longitude asc, station_type asc, station_model asc, weewx_info asc, python_info asc, platform_info asc, last_addr asc)');
        if(!$rc) {
            my $msg = 'create index failed: ' . $DBI::errstr;
            $dbh->disconnect();
            return ('FAIL', $msg, \%rec);
        }
    }

    # reject obvious attempts to spam the system

    my $last_seen = 0;
    $last_seen = $dbh->selectrow_array("select max(last_seen) from stations where last_addr=?", undef, ($rec{last_addr}));
    if($rec{last_seen} - $last_seen < $max_frequency) {
        $dbh->disconnect();
        return ('FAIL', 'too many updates attempted', \%rec);
    }

    my $urlcount = 0;
    $urlcount = $dbh->selectrow_array("select count(station_url) from (select station_url from stations where last_addr=? group by station_url)", undef, ($rec{last_addr}));
    if($urlcount > $max_urls) {
        $dbh->disconnect();
        return ('FAIL', 'too many station URLs from that address', \%rec);
    }

    # if data are different from latest record, save a new record.  otherwise
    # just update the timestamp of the matching record.

    my $sth = $dbh->prepare(q{insert or replace into stations (station_url,description,latitude,longitude,station_type,station_model,weewx_info,python_info,platform_info,last_addr,last_seen) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)});
    if(!$sth) {
        my $msg = 'prepare failed: ' . $DBI::errstr;
        $dbh->disconnect();
        return ('FAIL', $msg, \%rec);
    }
    $rc = $sth->execute($rec{station_url},$rec{description},$rec{latitude},$rec{longitude},$rec{station_type},$rec{station_model},$rec{weewx_info},$rec{python_info},$rec{platform_info},$rec{last_addr},$rec{last_seen});
    if(!$rc) {
        my $msg = 'execute failed: ' . $DBI::errstr;
        $dbh->disconnect();
        return ('FAIL', $msg, \%rec);
    }

    $dbh->disconnect();

    return ('OK', 'registration received', \%rec);
}

sub writereply {
    my($title, $status, $msg, $rec, $debug) = @_;

    my $tstr = &getformatteddate();
    &writecontenttype();
    &writeheader($title);
    print STDOUT "<p><strong>$title</strong></p>\n";
    print STDOUT "<pre>\n";
    print STDOUT "$status: $msg\n";
    print STDOUT "</pre>\n";
    if($rec && $debug) {
        print STDOUT "<pre>\n";
        foreach my $param (@params) {
            print STDOUT "$param: $rec->{$param}\n";
        }
        print STDOUT "last_addr: $rec->{last_addr}\n";
        print STDOUT "last_seen: $rec->{last_seen}\n";
        print STDOUT "user_agent: $rec->{user_agent}\n";
        print STDOUT "\n";
        print STDOUT "HTTP_REQUEST_METHOD: $ENV{HTTP_REQUEST_METHOD}\n";
        print STDOUT "HTTP_REQUEST_URI: $ENV{HTTP_REQUEST_URI}\n";
        print STDOUT "</pre>\n";
    }
    &writefooter($tstr);
}

sub get_summary_data {
    use DBI;
    my @platform_info;
    my @python_info;
    my @weewx_info;
    my @station_info;

    my $dbh = DBI->connect("dbi:SQLite:$db", q(), q(), {RaiseError => 0});
    if (!$dbh) {
        return "cannot connect to database: $DBI::errstr";
    }

    my $sth = $dbh->prepare("select station_type,station_model from stations group by station_model");
    if (!$sth) {
        return "cannot prepare select statement: $DBI::errstr";
    }
    $sth->execute();
    $sth->bind_columns(\my($st,$sm));
    while($sth->fetch()) {
        next if($st eq q() || $sm eq q());
        push @station_info, "$st,$sm";
    }
    $sth->finish();
    undef $sth;

    $sth = $dbh->prepare("select weewx_info from stations group by weewx_info");
    if (!$sth) {
        return "cannot prepare select statement: $DBI::errstr";
    }
    $sth->execute();
    $sth->bind_columns(\my($x));
    while($sth->fetch()) {
        next if($x eq q());
        push @weewx_info, $x;
    }
    $sth->finish();
    undef $sth;

    $sth = $dbh->prepare("select python_info from stations group by python_info");
    if (!$sth) {
        return "cannot prepare select statement: $DBI::errstr";
    }
    $sth->execute();
    $sth->bind_columns(\my($x));
    while($sth->fetch()) {
        next if($x eq q());
        push @python_info, $x;
    }
    $sth->finish();
    undef $sth;

    $sth = $dbh->prepare("select platform_info from stations group by platform_info");
    if (!$sth) {
        return "cannot prepare select statement: $DBI::errstr";
    }
    $sth->execute();
    $sth->bind_columns(\my($x));
    while($sth->fetch()) {
        next if($x eq q());
        push @platform_info, $x;
    }
    $sth->finish();
    undef $sth;

    $dbh->disconnect();
    undef $dbh;

    return (q(), \@platform_info, \@python_info, \@weewx_info, \@station_info);
}

sub summary {
    my(%rqpairs) = @_;

    my($errmsg, $plref, $pyref, $wref, $sref) = get_summary_data();
    if($errmsg ne q()) {
        &writereply('Database Failure', 'FAIL', $errmsg);
        return
    }

    my @platforms = @$plref;
    my @pythons = @$pyref;
    my @weewxs = @$wref;
    my @stations = @$sref;

    my $tstr = &getformatteddate();
    &writecontenttype();
    &writedoctype();
    &writehead('summary');
    print STDOUT "<body>\n";
    &dump_data('weewx', @weewxs);
    &dump_data('python', @pythons);
    &dump_data('stations', @stations);
    &dump_data('platforms', @platforms);

    &writefooter($tstr);
}

sub dump_data {
    my($title, @data) = @_;

    print STDOUT "<div>\n";
    print STDOUT "<h2>$title</h2>\n";
    foreach my $x (@data) {
        print STDOUT "$x<br/>\n";
    }
    print STDOUT "</div>\n";
}

sub get_history_data {
    use DBI;
    my @times;
    my @counts;
    my @stypes;

    my $dbh = DBI->connect("dbi:SQLite:$histdb", q(), q(), {RaiseError => 0});
    if (!$dbh) {
        return "cannot connect to database: $DBI::errstr";
    }

    my $sth = $dbh->prepare("select station_type from history group by station_type");
    if (!$sth) {
        return "cannot prepare select statement: $DBI::errstr";
    }
    $sth->execute();
    $sth->bind_columns(\my($st));
    while($sth->fetch()) {
        push @stypes, $st;
    }
    $sth->finish();
    undef $sth;

    $sth = $dbh->prepare("select datetime from history group by datetime order by datetime asc");
    if (!$sth) {
        return "cannot prepare select statement: $DBI::errstr";
    }
    $sth->execute();
    $sth->bind_columns(\my($ts));
    while($sth->fetch()) {
        push @times, $ts;
    }
    $sth->finish();
    undef $sth;

    foreach my $t (@times) {
	my %c;
	foreach my $s (@stypes) {
	    $c{$s} = 0;
	}
        my $sth = $dbh->prepare("select station_type,active,stale from history where datetime=$t");
        if (!$sth) {
            return "cannot prepare select statement: $DBI::errstr";
        }
        $sth->execute();
        $sth->bind_columns(\my($st,$active,$stale));
        while($sth->fetch()) {
	    $c{$st} = $active;
        }
        $sth->finish();
        undef $sth;
	push @counts, \%c;
    }

    $dbh->disconnect();
    undef $dbh;

    return q(), \@times, \@counts, \@stypes;
}

sub history {
    my(%rqpairs) = @_;

    my($errmsg, $tref, $cref, $sref) = get_history_data();
    if($errmsg ne q()) {
        &writereply('Database Failure', 'FAIL', $errmsg);
        return
    }

    my @times = @$tref;
    my @counts = @$cref;
    my @stations = @$sref;

    my $width = $rqpairs{width} ? $rqpairs{width} : 1200;
    my $height = $rqpairs{height} ? $rqpairs{height} : 1000;
    my $stacked = $rqpairs{stacked} eq '0' ? '0' : '1';
    my $sequential = $rqpairs{sequential} eq '1' ? '1' : '0';
    my $fill = $rqpairs{fill} eq '1' ? '1' : '0';

    my $tstr = &getformatteddate();
    &writecontenttype();
    print STDOUT <<EoB1;
<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 3.2 Final//EN\">
<html>
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
  <title>history</title>
  <script>
EoB1

    print STDOUT "var data = {\n";
    print STDOUT "time: [";
    for(my $i=0; $i<scalar(@times); $i++) {
        print STDOUT "," if $i > 0;
        print STDOUT "$times[$i]";
    }
    print STDOUT "],\n";
    print STDOUT "totals: [";
    for(my $i=0; $i<scalar(@times); $i++) {
        print STDOUT "," if $i > 0;
        print STDOUT "$counts[$i]{total}";
    }
    print STDOUT "],\n";
    print STDOUT "stations: [\n";
    foreach my $k (@stations) {
        next if $k eq 'total';
        print STDOUT "{ name: '$k', ";
        print STDOUT "values: [";
        for (my $j=0; $j<scalar(@times); $j++) {
            print STDOUT "," if $j > 0;
            print STDOUT "$counts[$j]{$k}";
        }
        print STDOUT "] },\n";
    }
    print STDOUT "]\n";
    print STDOUT "}\n";

    print STDOUT <<EoB2;
function draw_plot(width, height, stacked, sequential, fill) {
  var colors = [ '#ff0000', '#aa0000', '#660000', '#00aa00', '#005500',
                 '#0000ff', '#0000aa', '#000066', '#000000', '#888800',
                 '#00aaaa', '#008888', '#ff00ff', '#aa00aa', '#660066' ];
  var fills =  [ '#ffaaaa', '#aa7777', '#663333', '#00aa00', '#005500',
                 '#aaaaff', '#5555aa', '#222266', '#dddddd', '#888800',
                 '#00aaaa', '#008888', '#ff00ff', '#aa00aa', '#660066' ];
  var canvas = document.getElementById('history_canvas');
  canvas.width = width;
  canvas.height = height;
  var c = canvas.getContext('2d');
  c.font = '10px sans-serif';
  var hlabelbuf = 80;
  var vlabelbuf = 10;
  var haxisbuf = 20;
  var rpad = 5;
  var ticwidth = 4;
  var voffset = 50;
  var w = c.canvas.width;
  var h = c.canvas.height;
  var plotw = w - haxisbuf - hlabelbuf;
  var ploth = h - vlabelbuf*3 - voffset;
  var maxcnt = 0;
  if(stacked) {
    for(var i=0; i<data.totals.length; i++) {
      if(data.totals[i] > maxcnt) {
        maxcnt = data.totals[i];
      }
    }
  } else {
    for(var i=0; i<data.stations.length; i++) {
      for(var j=0; j<data.stations[i].values.length; j++) {
        if(data.stations[i].values[j] > maxcnt) {
          maxcnt = data.stations[i].values[j];
        }
      }
    }
  }
  var timemin = 9999999999999;
  var timemax = 0;
  for(var i=0; i<data.time.length; i++) {
    if(data.time[i] < timemin) {
      timemin = data.time[i];
    }
    if(data.time[i] > timemax) {
      timemax = data.time[i];
    }
  }
  var sorted = data.stations.sort(sort_by_count);
  var sums = Array(data.time.length);
  for(var i=0; i<sums.length; i++) { sums[i] = 0; }
  for(var i=0; i<sorted.length; i++) {
    for(var j=0; j<data.time.length; j++) {
      sums[j] += sorted[i].values[j];
    }
  }

  var y = ploth / maxcnt;
  var x = plotw / data.time.length;

  var used = Array();
  for(var i=0; i<sorted.length; i++) {
    c.fillStyle = fills[i%colors.length];
    c.strokeStyle = colors[i%colors.length];
    c.beginPath();
    c.moveTo(0, voffset+ploth);
    var xval = 0;
    var yval = 0;
    for(var j=0; j<data.time.length; j++) {
      if(sequential) {
        xval = x * j;
      } else {
        xval = plotw * (data.time[j] - timemin) / (timemax - timemin);
      }
      if(stacked) {
        yval = y * sums[j];
        sums[j] -= sorted[i].values[j];
      } else {
        yval = y * sorted[i].values[j];
      }
      c.lineTo(xval, voffset + ploth - yval);
    }
    if(fill) {
      c.lineTo(xval, voffset+ploth);
      c.fill();
    } else {
      c.stroke();
    }
    var yblk = voffset + ploth - vlabelbuf * Math.round(yval / vlabelbuf);
    while(used[yblk]) {
      yblk += vlabelbuf;
    }
/*    var yblk = voffset + ploth - yval; */
    c.fillStyle = colors[i%colors.length];
    var s = sorted[i].name;
    s += " (" + sorted[i].values[sorted[i].values.length-1] + ")";
    c.fillText(s, plotw+rpad, yblk);
    used[yblk] = 1;
  }

  var now = Math.round((new Date).getTime() / 1000);
  var starttime = data.time[0];

  /* change of accounting */
  var changetime = Math.round((new Date(2014,0,4,0,0,0,0)).getTime() / 1000);
  var v = plotw * (changetime - starttime) / (now - starttime);
  c.strokeStyle = "#dddddd";
  c.beginPath();
  c.moveTo(v+1, voffset);
  c.lineTo(v+1, voffset + ploth);
  c.stroke();

  /* horizontal and vertial axes */
  c.fillStyle = "#000000";
  c.strokeStyle = "#000000";
  c.beginPath();
  c.moveTo(1, voffset);
  c.lineTo(1, voffset+ploth);
  c.lineTo(plotw, voffset+ploth);
  c.stroke();

  /* horizontal axis */
  var inc = 604800; /* one week */
  for(var t=starttime; t<now; t+=inc) {
    var v = plotw * (t - starttime) / (now - starttime);
    c.strokeStyle = "#dddddd";
    c.beginPath();
    c.moveTo(v+1, voffset);
    c.lineTo(v+1, voffset+ploth);
    c.stroke();
    c.strokeStyle = "#000000";
    c.beginPath();
    c.moveTo(v+1, voffset+ploth);
    c.lineTo(v+1, voffset+ploth+ticwidth);
    c.stroke();
    var d = new Date(t*1000);
    var s = d.getUTCDate() + "." + (d.getUTCMonth()+1);
    c.fillText(s, v+1, voffset+ploth+vlabelbuf+5);
    if(d.getUTCMonth() == 0 && d.getUTCDate() < 8) {
      c.fillText(d.getUTCFullYear(), v+1, voffset+ploth+2*vlabelbuf+5);
    }
  }

  /* vertical axis */
  var edge = w - haxisbuf;
  for(var j=0; j*y<ploth; j++) {
    c.beginPath();
    c.moveTo(edge-1, voffset+ploth-j*y);
    c.lineTo(edge-ticwidth, voffset+ploth-j*y);
    if(j%5 == 0) {
      c.lineTo(edge-ticwidth*2, voffset+ploth-j*y);
      c.fillText(j, edge+2, voffset+ploth-j*y);
    }
    c.stroke();
  }

  /* title */
  c.fillStyle = "#000000";
  var sd = new Date(starttime*1000);
  var ed = new Date(now*1000);
  var s = sd.getUTCDate() + "." + (sd.getUTCMonth()+1) + "." + sd.getUTCFullYear();
  s += " to ";
  s += ed.getUTCDate() + "." + (ed.getUTCMonth()+1) + "." + ed.getUTCFullYear();
  c.fillText(s, 10, 30);
  c.font = '20px sans-serif';
  c.fillText('Stations Running WeeWX', 10, 18);
}

function sort_by_name(a,b) {
  if(a.name < b.name)
    return -1;
  if(a.name > b.name)
    return 1;
  return 0;
}

function sort_by_count(a,b) {
  if(a.values[a.values.length-1] < b.values[b.values.length-1])
    return 1;
  if(a.values[a.values.length-1] > b.values[b.values.length-1])
    return -1;
  return 0;
}
  </script>
</head>
<body onload='draw_plot($width,$height,$stacked,$sequential,$fill);'>
<canvas id='history_canvas'></canvas>
<br/>
EoB2

    &writefooter($tstr);
}

sub writecontenttype {
    my($type) = @_;

    $type = "text/html" if $type eq "";
    print STDOUT "Content-type: text/html\n\n";
}

sub writedoctype() {
    print STDOUT "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 3.2 Final//EN\">\n";
}

sub writehead() {
    my($title,$style,$script) = @_;

    if(! $style ne q()) {
        $style = "\
<style>\
  body {\
      font-family: Verdana, Arial, Helvetica, sans-serif;\
      font-size: 0.8em;\
    color: #000000;\
  background-color: #ffffff;\
}\
  </style>\
";
    }

    if($script ne q()) {
        $script = "<script>\n$script\n</script>\n";
    }

    print STDOUT <<EoB;
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
  <title>$title</title>
$style
$script
</head>
EoB
}

sub writeheader {
    my($title,$head) = @_;

    print STDOUT "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 3.2 Final//EN\">\n";
    print STDOUT "<html>\n";
    print STDOUT "<head>\n";
    print STDOUT "  <title>$title</title>\n";
    print STDOUT "$head\n";
    print STDOUT "</head>\n";
    print STDOUT "<body>\n";
};

sub writefooter {
    my($mdate) = @_;

    if($mdate) {
        print STDOUT "<p>\n";
        print STDOUT "<small><i>\n";
        print STDOUT "$mdate<br/>\n";
        print STDOUT "$version<br/>\n";
        print STDOUT "</i></small>\n";
        print STDOUT "</p>\n";
    }

    print STDOUT "\n</body>\n</html>\n";
}

sub getformatteddate {
    return strftime $DATE_FORMAT, gmtime time;
}

sub getrequest {
    my $request = q();
    if ($ENV{'REQUEST_METHOD'} eq "POST") {
        read(STDIN, $request, $ENV{'CONTENT_LENGTH'});
    } elsif ($ENV{'REQUEST_METHOD'} eq "GET" ) {
        $request = $ENV{'QUERY_STRING'};
    }
    my $delim = ',';
    my %pairs;
    foreach my $pair (split(/[&]/, $request)) {
        $pair =~ tr/+/ /;
        $pair =~ s/%(..)/pack("c",hex($1))/ge;
        my($loc) = index($pair,"=");
        my($name) = substr($pair,0,$loc);
        my($value) = substr($pair,$loc+1);
        if($pairs{$name} eq "") {
            $pairs{$name} = $value;
        } else {
            $pairs{$name} .= "${delim}$value";
        }
    }
    return($ENV{'QUERY_STRING'},%pairs);
}
