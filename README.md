# ultimaker-s5-timelapse
A script to automatically recover timelapses from 3D 
Each timelapse metadata is stored in a local SQLite database.

`ultimaker-s5-timelapse` was created by [Clément Chaine](https://github.com/cchaine)

## Requirements

```
python >= 2.7
ffmpeg >= 4.1.1
```

## Usage

Your Ultimaker S5 printer and your computer need to be connected to the same network.
```
usage: python ultimaker_s5_timelapse [-h] -ip IP

    IP is the local ip address of your printer
```
