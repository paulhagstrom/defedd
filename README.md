defedd
======

Disk image conversion from EDD captures to something more useful

I'll write up more docs later, the code has a lot of comments in it.
Basic idea here is to convert EDD files captured on an Apple II with I'm fEDD Up into formats an emulator can use.
One of the options is just to dump pretty much the raw file into an FDI file
This tends to work pretty well in OpenEmulator
Goal is to get MFI (MESS floppy images) working.
This requires finding the track, EDD samples a track 2.5 times.
That's the hard part.
This will also analyze the disk to handle simple 16-sector disks
Can write dsk and nib files fairly reliably
MFI is only kind of there.  Haven't got it to work yet.
