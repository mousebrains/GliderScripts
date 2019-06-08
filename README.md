# GliderScripts
This is a collection of my glider related scripts. Most are for syncing from one machine to another.

1) sync2osudock is a bash script which uses inotifywait to trigger itself to rsync a directory to a target machine
2) sync68X.service are various services which invoke sync2osudock
3) syncCache.py uses inotifywait to trigger syncing SFMC/TWR/Slocum cache files to a target machine
4) syncCache2vm3.services is a service which invokes syncCache.py
5) syncGMC.py uses inotifywait to trigger syncing SFMC/twr/Slocum glider directories, from-glider, to-glider, ... to a target machine. It flattens out the group in the process that SFMC uses.
6) syncGMC2*.servce are example services using syncGMC.py
