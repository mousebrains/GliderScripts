# GliderScripts
This is a collection of my glider related scripts. Most are for syncing from one machine to another.

This set syncs from an SFMC machine to other machines:

1) sync2osudock is a bash script which uses inotifywait to trigger itself to rsync a directory to a target machine
2) sync68X.service are various services which invoke sync2osudock
3) syncCache.py uses inotifywait to trigger syncing SFMC/TWR/Slocum cache files to a target machine
4) syncCache2vm3.services is a service which invokes syncCache.py
5) syncGMC.py uses inotifywait to trigger syncing SFMC/twr/Slocum glider directories, from-glider, to-glider, ... to a target machine. It flattens out the group in the process that SFMC uses.
6) syncGMC2*.servce are example services using syncGMC.py

This set syncs from non-SFMC machines to SFMC machines:

1) sync2SFMC.py syncs ma files to an SFMC machine. Currently only goto files are supported.
2) sync2FMC0.service.* are examples of services scripts using sync2SFMC.py
3) probar.py is a reactive test script for the SAS experiment. It writes an sbd/tbd into a directory then monitors a directory for new goto files. When a goto file is found the next sbd/tbd files are distributed, ...
4) probar.service is an example service using probar.py
