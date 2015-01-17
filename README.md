defedd
======

Disk image conversion from EDD captures to something more useful

Someday I will spend some actual time on this README.  At the moment, this is basically under constant development.

The basic idea is this, though.  Using I'm fEDD Up:

http://www.brutaldeluxe.fr/products/apple2/imfEDDup/

in combination with an EDD4+ card:

https://ultimateapple2.com/catalogzenQI/index.php?main_page=product_info&products_id=2

an Apple II disk can be captured into an EDD file that contains a low-level bit read of the tracks.

This script is for converting those EDD files into something more useful that an emulator can read.

Right now it can convert to .dsk images (most Apple II emulators, for unprotected disks), .nib (most Apple II emulators, for very lightly protected disks), .v2d (Virtual II, a nibble file that allows for half-track resolution and variable-length tracks), .fdi (floppy disk image, usable in Open Emulator).

It does not yet convert to MFI (MESS floppy image, for MESS), but that is one of the goals, and the code for that is partly in but disabled.

It does a lot of analysis and can be quite slow.

It is impossible to get tracks synced perfectly because there is no signal to tell you where you are on the disk.  Some attempts to estimate track advance are made, but it's pretty rough and unreliable.  Disks that require sync may have to be synced by hand individually.

The EDD file contains approximately 2.5 samples of each track, and this script attempts to use them to reconcile the bits.

To see the options, use -h.

To make a fairly quick .fdi file that Open Emulator can use (and which often will work), use options -faq.  This will send all 2.5x samples into an .fdi file.

This assumes the EDD files are at quarter-track resolution.
