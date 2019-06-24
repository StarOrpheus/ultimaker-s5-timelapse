# ultimaker-s5-timelapse

A script to automatically recover timelapses from 3D prints and store metadata in a local SQLite database.

`ultimaker-s5-timelapse` was created by [Clément Chaine](https://github.com/cchaine)

## Requirements

```
python >= 2.7
ffmpeg >= 4.1.1
sqlite >= 3.14
```

## Usage

Both the Ultimaker S5 printer and the computer need to be connected to the same network.
```
usage: python ultimaker_s5_timelapse.py [-h] -ip IP

    IP is the local ip address of your printer
```
