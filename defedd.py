#!/usr/bin/env python3

import sys
import zlib
import getopt
import struct
import math
import time

# Paul Hagstrom, started August 2014
# First attempt at using Python, so brace yourself for the occasional non-Pythonic dumbness.
# Current status: Can do dsk, nib, fdi
# mfi untested, whole tracks only so far.
# I tightened up some of the loops and it helped quite a bit
# Choplifter only works with no translation fdi files.
# Wizardry doesn't work
# Snack Attack doesn't work
# I've been playing around tweaking things, ways to make output clearer
# also the track match, which now simply checks for about 95% match within the region checked
# Still not working consistently, wish I knew what makes the difference between good and bad
# Perhaps try to add a parameter file so that I can set the behavior of individual tracks
# so I can manually try things with trial and error until something works and try to figure out
# why.  Guess in the meantime I could hardcode things in here for testing.

# Snack Attack parm guides just give deprotection info (CLC in nibble check I think).
# Wizardry is supposed to have boot disk write protected.
# Copts and Robbers: 0 addr DDAADA data MAX=25? sync; 1.5-13/15.5 by 1 sync
# Choplifter complex: 0, 1-8, 9, A-B, C-1E.5 by .5, 20 CII+



# options will be stored globally for retrievability
options = {'write_nib': False, 'write_dsk': False, 'write_mfi': False, 'write_fdi': False, 'write_log': False,
		'process_fractional': True, 'analyze_sectors': True, 'write_full': False, 'no_translation': False,
		'verbose': False, 'werbose': False, 'console': [sys.stdout], 'repair_tracks': True, 'use_second': False,
		'use_slice': False, 'from_zero': False, 'write_protect': False}

def main(argv=None):
	'''Main entry point'''
	global options

	print("defedd - analyze and convert EDD files.")

	try:
		opts, args = getopt.getopt(sys.argv[1:], "hnd1fmqacvwlk20sp", \
			["nib", "dsk", "fdi", "mfi", "int", "quick", "cheat", "all", "verbose", "werbose", "log", "keep", "second", "zero", "slice", "protect"])
	except getopt.GetoptError as err:
		print(str(err))
		usage()
		return 1
	for o, a in opts:
		if o == "-h":
			usage()
			return 0
		elif o == "-f" or o == "--fdi":
			options['write_fdi'] = True
			print("Will save fdi file.")
		elif o == "-m" or o == "--mfi":
			options['write_mfi'] = True
			print("Will save mfi file.")
		elif o == "-n" or o == "--nib":
			options['write_nib'] = True
			print("Will save nib file.")
		elif o == "-d" or o == "--dsk":
			options['write_dsk'] = True
			print("Will save dsk file.")
		elif o == "-l" or o == "--log":
			options['write_log'] = True
			print("Will save log file.")
		elif o == "-1" or o == "--int":
			options['process_fractional'] = False
			print("Will process only whole tracks.")
		elif o == "-q" or o == "--quick":
			options['analyze_sectors'] = False
			print("Will skip sector search.")
		elif o == "-c" or o == "--cheat":
			options['write_full'] = True
			print("Cheat and write full EDD 2.5x sample if can't find track boundary.")
		elif o == "-k" or o == "--keep":
			options['repair_tracks'] = False
			print("Will not attempt to repair bitstream.")
		elif o == "-2" or o == "--second":
			options['use_second'] = True
			print("Will use second track copy in sample.")
		elif o == "-a" or o == "--all":
			options['no_translation'] = True
			print("Will write full tracks for all tracks.")
		elif o == "-0" or o == "--zero":
			options['from_zero'] = True
			print("Will write track-length bits starting from beginning of EDD sample for all tracks.")
		elif o == "-s" or o == "--slice":
			options['use_slice'] = True
			print("Will write track-length bits starting from beginning of EDD sample for unparseable tracks")
		elif o == "-p" or o == "--protect":
			options['write_protect'] = True
			print("Will write image as write protected if supported (FDI)")
		elif o == "-v" or o == "--verbose":
			options['verbose'] = True
			print("Will be more chatty about progress than usual.")
		elif o == "-w" or o == "--werbose":
			options['verbose'] = True
			options['werbose'] = True
			print('''
It was a dark and stormy night.  On the screen, a cursor in a terminal window
glowed invitingly, like a candle behind a frosty ground-floor window of a
run-down Victorian inn.  The inn had seen better days.  Travelers were few and
far between now that the railway station had closed, prospective lodgers being
whisked onward to the rambunctious squalor of the larger nearby cities.  The
wind whistled angrily, pushing a draft through the deteriorating walls and
causing the candle to flicker, much like a cursor in a dark terminal window.
Our story begins with a single command, cautiously typed at a prompt. . .
''')

	try:
		eddfilename = args[0]
	except:
		print('You need to provide the name of an EDD file to begin.')
		return 1
	options['nibfilename'] = eddfilename + ".nib"
	options['dskfilename'] = eddfilename + ".dsk"
	options['mfifilename'] = eddfilename + ".mfi"
	options['fdifilename'] = eddfilename + ".fdi"
	options['logfilename'] = eddfilename + ".log"

	# Do some sanity checking
	if options['process_fractional'] and not options['write_mfi'] and not options['write_fdi']:
		options['process_fractional'] = False
		print('Only processing whole tracks, no sense in processing fractional tracks unless they will be stored.')
	# TODO: Maybe there is other sanity checking to do here, add if it occurs to me

	# TODO: Maybe at some point write out the images as we process each track rather than keeping whole disk in memory.
	with open(eddfilename, mode="rb") as eddfile:
		if options['write_log']:
			options['console'].append(open(options['logfilename'], mode="w"))
		tracks = []
		current_track = 0.0
		while True:
			track_start_clock = time.clock()
			eddbuffer = eddfile.read(16384)
			if eddbuffer:
				if options['process_fractional'] or current_track == int(current_track):
					track = {'track_number': current_track}
					track['index_offset'] = 0 # bit position of the index pulse
					# get track bits and parse them into nibbles
					track['bits'] = bytes_to_bits(eddbuffer)
					nibbles = nibblize(track['bits'])
					track['nibbles'] = nibbles['nibbles']
					track['offsets'] = nibbles['offsets']
					track['nibbits'] = nibbles['nibbits']
					track['nits'] = nibbles['nits']
					# Analyze track for standard 13/16 formats, for dsk and repeat hinting
					if options['analyze_sectors']:
						track = consolidate_sectors(locate_sectors(track))
					if options['write_fdi'] or options['write_mfi']:
						# this bit level repeat finding is slow and not necessary for dsk/nib
						# Find areas of sync nibbles for repeat hinting
						track = find_sync(track)
						track = find_repeats(track)
					track['processing_time'] = time.clock() - track_start_clock
					track_status(track)
					tracks.append(track)
			else:
				break
			current_track += 0.25

		if options['write_nib']:
			write_nib_file(eddfile, tracks)
		if options['write_dsk']:
			write_dsk_file(eddfile, tracks)
		if options['write_fdi']:
			write_fdi_file(eddfile, tracks)
		if options['write_mfi']:
			write_mfi_file(eddfile, tracks)
		if options['write_log']:
			(options['console'])[1].close
	return 1

def track_status(track):
	'''Display information about track analysis'''
	sectors = " {:2d} sectors".format(len(track['all_sectors'])) if 'all_sectors' in track else ''
	match = " {:6d} bitmatch".format(track['match_bits']) if 'match_bits' in track else ''
	bits = " {:6d} trackbits".format(track['data_bits']) if 'data_bits' in track else ''
	needle = " {:5d} bitstart".format(track['match_needle']) if 'match_needle' in track else ''
	hits = " {!s} hits".format(track['match_hits']) if 'match_hits' in track else ''
	trk = "{:5.2f}:".format(track['track_number'])
	proc = " {:5.2f}s".format(track['processing_time'])
	message(trk + sectors + match + bits + needle + proc + hits)

# A message sent at level 0 (default) is always displayed
# level 1 is displayed in verbose mode, level 2 is displayed in werbose mode
# Any messages go both to the screen and the log file if the log file is requested
def message(message, level=0, end='\n'):
	'''Output messages to the screen and to the log file if requested'''
	global options
	if level == 0 or (level == 1 and options['verbose']) or (level == 2) and options['werbose']:
		for output in options['console']:
			print(message, file=output, end=end)

def usage():
	'''Display help information'''
	print('''
Usage: defedd.py [options] eddfile

Assumption is that the EDD file was produced by I'm fEDD Up.
Quarter tracks.

Options:
 -h, --help    You're looking at it.
 -q, --quick   Skip standard sector analysis, ok for fdi/mfi/nib
 -1, --int     Consider only whole tracks (not quarter tracks)
 -c, --cheat   Write full 2.5x bit read for unparseable tracks (vs. unformatted)
 -a, --all     Write full 2.5x bit read for all tracks (i.e. cheat everywhere)
 -s, --slice   Write EDD bits to track length for unparseable tracks (cheat lite)
 -0, --zero    Write EDD bits from 0 instead of found track (slice for formatted)
 -k, --keep    Do not attempt to repair bitstream
 -2, --second  Use second track repeat if choice is needed (default is first)
 -d, --dsk     Write .dsk file (data-only 16-sector standard images)
 -n, --nib     Write .nib file (for 13-sectors and light protection)
 -m, --mfi     Write .mfi file (MESS Floppy image simulated flux image)
 -f, --fdi     Write .fdi file (bitstream, cheated images ok in OpenEmulator)
 -l, --log     Write .log file of conversion output
 -v, --verbose Be more verbose than usual
 -w, --werbose Be way, way (ponponpon) more verbose than usual (implies -v)
 	''')
	return

def write_dsk_file(eddfile, tracks):
	'''Write the data out in the form of a 34-track dsk file'''
	global options
	with open(options['dskfilename'], mode="wb") as dskfile:
		for track in tracks:
			if (4 * track['track_number']) % 4 == 0 and track['track_number'] < 35:
				dskfile.write(track['track_bytes'])

def write_nib_file(eddfile, tracks):
	'''Write the data out in the form of a 34-track nib file'''
	global options
	with open(options['nibfilename'], mode="wb") as nibfile:
		for track in tracks:
			if (4 * track['track_number']) % 4 == 0 and track['track_number'] < 35:
				if 'sync_nibstart' in track:
					sync_nibstart = track['sync_nibstart']
					nibfile.write((track['nibbles'])[sync_nibstart: sync_nibstart + 0x1a00])
				else:
					nibfile.write((track['nibbles'])[:0x1a00])

def write_fdi_file(eddfile, tracks):
	'''Write the data out in the form of an FDI file'''
	global options
	with open(options['fdifilename'], mode="wb") as fdifile:
		# Write the FDI header
		fdifile.write(b"Formatted Disk Image file\n\r") #signature
		fdifile.write(b"defedd, version 0.0a          \n\r") #creator
		for x in range(81): # comment field and eof marker
			fdifile.write(b"\x1a") 
		fdifile.write(b"\x02\x00") #version 2.0
		fdifile.write(b"\x00\x9f") #last track for OE, corresponds to 160 quarter tracks, or 40 tracks
		fdifile.write(b"\x00") #last head
		fdifile.write(b"\x01") #5.25
		fdifile.write(b"\xac") #300 rpm
		if options['write_protect']:
			fdifile.write(b"\x01") #flags, not write protected, not index synchronized
		else:
			fdifile.write(b"\x00") #flags, not write protected, not index synchronized
		fdifile.write(b"\x05") #192 tpi (quarter tracks)
		fdifile.write(b"\x05") #192 tpi (quarter tracks, though the heads aren't really this narrow)
		fdifile.write(b"\x00\x00") #reserved
		for track in tracks:
			phase = (4 * track['track_number']) % 4
			if options['process_fractional'] or phase == 0:
				fdifile.write(b"\xd2") # raw GCR
				if track['data_bits'] == 0:
					# treat track as unformatted (so we don't even have the 8 header bits)
					fdifile.write(b'\x00\x00')
				else:
					track['fdi_write_length'] = 8 + len(track['fdi_bytes'])
					track['fdi_page_length'] = math.ceil(track['fdi_write_length'] / 256)
					fdifile.write(bytes([track['fdi_page_length']]))
			if phase == 0 and not options['process_fractional']:
				# write zeros for lengths of quarter tracks
				fdifile.write(b'\x00\x00\x00\x00\x00\x00')
		# Write out enough zeros after the track data to get us to a page boundary
		if options['process_fractional']:
			tracks_written = len(tracks)
		else:
			tracks_written = 4 * len(tracks)
		for extra_track in range(20 + 160 - tracks_written):
			fdifile.write(b"\x00\x00")

		# go to the beginning of the eddfile in case we want to write bytes straight out of it
		eddfile.seek(0)

		for track in tracks:
			track_index = track['track_number'] * 4
			phase = track_index % 4
			if options['process_fractional'] or phase == 0:
				if track['data_bits'] > 0:
					fdifile.write(struct.pack('>L', track['data_bits']))
					fdifile.write(struct.pack('>L', track['index_offset']))
					if options['from_zero']:
						# if asked, we can at this point pass bits straight from the EDD file
						# I am allowing this on the suspicion that it might preserve a little bit
						# more inter-track sync information for track arcing.
						eddbuffer = eddfile.read(16384)
						fdifile.write(eddbuffer[:track['data_bits']])
					else:
						# bitstream data could actually come straight out of the EDD file
						# but I will use the one that was re-encoded based on repeat location
						fdifile.write(track['fdi_bytes'])
					# pad to a page boundary.
					for x in range(256 - track['fdi_write_length'] % 256):
						fdifile.write(b"\x00")

def write_mfi_file(eddfile, tracks):
	'''Write the data out in the form of a MESS Floppy Image file'''
	global options
	with open(options['mfifilename'], mode="wb") as mfifile:
		# Preprocess the tracks because we need this information for the header
		# Don't have the same option of storing 2.5x revolutions of bits in MFI
		# So, we need to use the track section we identified.
		eddfile.seek(0)
		current_track = 0.0
		while False:
			if eddbuffer:
				track_index = current_track * 4
				phase = track_index % 4
				# TODO: allow for quarter tracks when the container supports it
				if phase == 0:
					track = tracks[int(track_index)]
					haystack_offset = track['haystack_offset']
					track_length = haystack_offset - track[needle_offset]
					if track_length > 52000:
						haystack_offset = track[needle_offset] + 52000
					track_bits = (track['bits'])[track['needle_offset']: track['haystack_offset']]
					start_bit = 0
					# TODO: Allow for positioning of the start bit with something sensible.
					cell_length = math.floor(2000000 / len(track_bits))
					if cell_length % 2 == 1:
						cell_length -= 1
					mfi_bits = track['bits']
					running_length = 0
					zero_span = cell_length
					level_a = True
					odd_trans = False
					mfi_track = []
					mg_b = 1 << 28
					for bit in track['bits']:
						if bit == 1:
							if level_a:
								mfi_track.append(struct.pack('>L', zero_span + mg_b))
							else:
								mfi_track.append(struct.pack('>L', zero_span))
							running_length += zero_span
							zero_span = cell_length
							odd_trans = not odd_trans
							level_a = not level_a
						else:
							zero_span += cell_length
					pad = (200000000 - running_length)
					if odd_trans and level_a:
						pad += mg_b
					mfi_track.append(struct.pack('>L', pad))
					mfi_track_z = zlib.compress(mfi_track)
					mfitrackdata.append(mfi_track_z)
					mfitracklength.append(len(mfi_track))
					print('Track {} uncompressed {}, compressed {}'.format(current_track, len(mfi_track), len(mfi_track_z)))
					tracks_to_do = 35
					mfifile.write(b"MESSFLOPPYIMAGE\x00") #signature
					mfifile.write(struct.pack('>L', 35)) #last track
					mfifile.write(struct.pack('>L', 1)) #last head
					mfifile.write(b"525 ") #form factor
					mfifile.write(b"SSDD") #variant
					current_offset = 16 + 16 + (16 * tracks_to_do)
					for track_number in range(0, tracks_to_do):
						if mfitracklength[track] > 0:
							mfifile.write(struct.pack('>L', current_offset))
							mfifile.write(struct.pack('>L', len(mfitrackdata[track]))) #compressed length in bytes
							mfifile.write(struct.pack('>L', mfitracklength[track])) #uncompressed length in bytes
							mfifile.write(struct.pack('>L', 1000)) #write splice, arbitrarily picked at 1000
							current_offset += mfitrackdata[track].length
						else:
							# if the track does not exist (e.g., we need track 34.5 but have only to 34), write empty track
							mfifile.write(struct.pack('>L', current_offset))
							mfifile.write(struct.pack('>L', 0)) #compressed length in bytes
							mfifile.write(struct.pack('>L', 0)) #uncompressed length in bytes
							mfifile.write(struct.pack('>L', 0)) #write splice, arbitrarily picked at 0
					# write the MFI track data itself
					for track_number in range(0, tracks_to_do):
						if mfitrackdata[track]:
							mfifile.write(mfitrackdata[track])
			else:
				break

def bytes_to_bits(eddbuffer):
	'''Convert bytes into component bits'''
	bits = bytearray()
	offset = 0
	for byte in eddbuffer:
		binbyte = bin(byte)[2:] # cuts off the 0x from the beginning
		bytebits = [int(bit) for bit in ('00000000'[len(binbyte):] + binbyte)]
		bits.extend(bytebits)
	return bits

def nibblize(bits):
	'''Convert track bits into nibbles by emulating the Disk II controller'''
	nibbles = bytearray()
	offsets = []
	nibbits = []
	nits = []
	offset = 0
	nibblebits = ""
	data_register = 0
	wait_for_one = True
	for bit in bits:
		if bit == 1:
			nibblebits += "1"
			data_register = (data_register << 1) + 1
			wait_for_one = False
		else:
			if wait_for_one:
				nibblebits += "-"
			else:
				nibblebits += "0"
				data_register = data_register << 1
		if data_register > 127:
			wait_for_one = True
			nibbles.append(data_register)
			offsets.append(offset)
			nibbits.append(nibblebits)
			nits.append(len(nibblebits))
			nibblebits = ""
			data_register = 0
		offset += 1
	return {'nibbles': nibbles, 'offsets': offsets, 'nibbits': nibbits, 'nits': nits}

# This is primarily for the purpose of creating dsk images
# Also useful for getting an estimate of track length.
# Of course, this is mostly useful on disks with pretty much standard formatting.
# TODO: Maybe at some point I might make it an option to look for nonstandard marks,
# though they will not be helpful in creating dsk images.
def locate_sectors(track):
	'''Scan track structure for sector information'''
	# We will collect every sector we find into all_sectors
	all_sectors = []
	# A sector with minimal information (used if we find a data mark without an address mark)
	zero_sector = {'dos32': False, 'addr_checksum_ok': False}
	message('Scanning track for address and data marks.', 2)
	# TODO: Keep track of the gaps and optimal beginning of the nibble stream for nib writing.
	# Skip the last 420 nibbles since they cannot contain a sector and this would be their third read anyway
	stop_scan = len(track['nibbles']) - 420
	offset = 0
	awaiting_data = False
	# We will keep track of the gaps between found elements, might be useful at least informationally.
	gap = bytearray()
	while offset < stop_scan:
		nibfield = (track['nibbles'])[offset : offset + 14]
		if nibfield[0:3] in [bytearray(b'\xd5\xaa\x96'), bytearray(b'\xd5\xaa\xb5')]:
			sector = {
			'dos32': (nibfield[2] == 0xb5),
			'offset': offset,
			'vol': ((nibfield[3] << 1)+1) & nibfield[4], 
			'track': ((nibfield[5] << 1)+1) & nibfield[6], 
			'sector': ((nibfield[7] << 1)+1) & nibfield[8], 
			'addr_checksum': ((nibfield[9] << 1)+1) & nibfield[10],
			'addr_pre_gap': gap,
			'addr_epilogue': nibfield[11:14]
			}
			sector['addr_checksum_ok'] = (sector['addr_checksum'] == (sector['vol'] ^ sector['track'] ^ sector['sector']))
			sector['addr_epilogue_ok'] = (sector['addr_epilogue'][0:2] == bytearray(b'\xde\xaa'))
			sector['addr_epilogue_perfect'] = (sector['addr_epilogue'][0:3] == bytearray(b'\xde\xaa\xeb'))
			all_sectors.append(sector)
			gap = bytearray()
			if awaiting_data:
				# If we have gotten two address fields in a row, send a linebreak
				message('', 2)
			message('{:6d} ADDR: {:02x} {:02x} {:02x} {} {} {}{}  '.format( \
				sector['offset'], sector['vol'], sector['track'], sector['sector'], \
				'13' if sector['dos32'] else '16', \
				'   ' if sector['addr_checksum_ok'] else 'CHK', \
				'    ok' if sector['addr_epilogue_ok'] else ('{:02x}{:02x}{:02x}'.format( \
					(sector['addr_epilogue'])[0], (sector['addr_epilogue'])[1], (sector['addr_epilogue'])[2])), \
				'!' if sector['addr_epilogue_perfect'] else ' ' \
				), 2, end='')
			# jump past the address epilogue
			offset += 14
			# next thing we expect is a data field
			awaiting_data = True
		elif nibfield[0:3] == bytearray(b'\xd5\xaa\xad'): # data mark
			# this is presumed to be the data mark on the last pushed sector
			if awaiting_data:
				sector = all_sectors.pop()
			else:
				# we got a data field without having registered an address field
				sector = zero_sector
				message('{:6d}                                '.format(offset), 2, end='')
			# the next 342 (3.3) or 410 (3.2) nibbles will be encoded data, followed by a checksum and epilogue
			data_length = 411 if sector['dos32'] else 343
			nibfield = track['nibbles'][offset + 3: offset + data_length + 6]
			sector['encoded_data'] = nibfield[:-3]
			sector['data_epilogue'] = nibfield[-3:]
			sector['data'] = decode_53(sector['encoded_data']) if sector['dos32'] else decode_62(sector['encoded_data'])
			sector['data_checksum'] = sector['data'].pop()
			sector['data_checksum_ok'] = (sector['data_checksum'] == 0)
			sector['data_epilogue_ok'] = (sector['data_epilogue'][0:2] == bytearray(b'\xde\xaa'))
			sector['data_epilogue_perfect'] = (sector['data_epilogue'][0:3] == bytearray(b'\xde\xaa\xeb'))
			sector['data_pre_gap'] = gap
			# put the sector back, now with the data
			all_sectors.append(sector)
			gap = bytearray()
			awaiting_data = False
			message('DATA: {} {}{}'.format( \
				'   ' if sector['data_checksum_ok'] else 'CHK', \
				'ok    ' if sector['data_epilogue_ok'] else ('{:02x}{:02x}{:02x}'.format( \
					(sector['data_epilogue'])[0], (sector['data_epilogue'])[1], (sector['data_epilogue'])[2])), \
				'!' if sector['data_epilogue_perfect'] else ' ' \
				), 2)
			offset += 6 + data_length
		else:
			# Keep track of the building gap between marks we find
			gap.append(track['nibbles'][offset])
			offset += 1
	track['all_sectors'] = all_sectors
	if awaiting_data:
		# if we ended after an address without data, print a linebreak
		message('', 2)
	return track

def dos_order(logical_sector):
	'''DOS 3.3 sector skewing'''
	return {
		0x00: 0x00, 0x01: 0x0d, 0x02: 0x0b, 0x03: 0x09, 0x04: 0x07, 0x05: 0x05, 0x06: 0x03, 0x07: 0x01,
		0x08: 0x0e, 0x09: 0x0c, 0x0a: 0x0a, 0x0b: 0x08, 0x0c: 0x06, 0x0d: 0x04, 0x0e: 0x02, 0x0f: 0x0f,
		}[logical_sector]

def consolidate_sectors(track):
	'''Consolidate all the sectors we found into a standard 13/16 for writing to dsk'''
	global options
	sorted_sectors = {}
	dos32_mode = False
	if options['werbose']:
		message('Consolidating found sectors by reported sector number and checking data integrity.')
	for found_sector in track['all_sectors']:
		if found_sector['addr_checksum_ok']:
			# if any sector is in DOS 3.2 mode, presume the whole track is
			if found_sector['dos32']:
				dos32_mode = True
			try:
				sorted_sectors[found_sector['sector']].append(found_sector)
			except:
				sorted_sectors[found_sector['sector']] = [found_sector]
	# look for the bit distance between copies.
	# This will be useful in guessing the track length in the repeat scan.
	# TODO: the results should be basically consistent, but differences could help isolate bit slips
	# However, unlikely to both need to correct bit slips and have identifiable sectors.
	# So it might be interesting to see how reliable the EDD image is, but not much help with protections.
	# Strategy here is to look for the shortest bit distance, but that wasn't based on much thought.
	# Unsure whether longer would be better but if this is just used as the starting point for a search,
	# shortest is best.
	predicted_track_bits = 999999
	for sector_number in sorted_sectors.keys():
		base_copy = None
		for copy in sorted_sectors[sector_number]:
			if base_copy:
				# if copy['data'] and not base_copy['data'] == copy['data']:
				# 	print('Data mismatch between copies of sector ' + str(sector_number))
				# bit_distance = 8 * (copy['offset'] - base_copy['offset'])
				bit_distance = ((track['offsets'])[copy['offset']] - (track['offsets'])[base_copy['offset']])
				if bit_distance < predicted_track_bits:
					predicted_track_bits = bit_distance
			else:
				base_copy = copy
	# If we found a reasonable number of predicted track bits, store for use in repeat scan
	if 50000 > predicted_track_bits > 53000:
		track['predicted_track_bits'] = 50000
	if options['werbose']:
		for sector_number in sorted_sectors.keys():
			data = False
			message('Sec {:0x}: '.format(sector_number), 2, end='')
			for sector in sorted_sectors[sector_number]:
				if data:
					data_match = True if 'data' in sector and sector['data'] == data else False
					bit_distance = sector['offset'] - offset
				else:
					data = sector['data'] if 'data' in sector else False
					bit_distance = 0
					data_match = True
				offset = sector['offset']
				message('{} {} {} {:5d} {:5d} /'.format( \
					'    ' if 'addr_checksum_ok' in sector and sector['addr_checksum_ok'] else 'ACHK', \
					'    ' if 'data_checksum_ok' in sector and sector['data_checksum_ok'] else 'DCHK', \
					'    ' if data_match else 'DATA', \
					sector['offset'], bit_distance
					), 2, end='')
			message('', 2)
	# For now, I will just take the first valid one found
	track_bytes = bytearray()
	track_ok = True
	for logical_sector in range(16):
		# TODO: Allow for CP/M, Pascal, ProDOS skewing as well at some point
		physical_sector = logical_sector if dos32_mode else dos_order(logical_sector)
		try:
			sector = sorted_sectors[physical_sector][0]
			if sector['data_checksum_ok']:
				track_bytes.extend(sector['data'])
			else:
				track_bytes.extend(bytearray(256))
				track_ok = False
		except:
			track_bytes.extend(bytearray(256))
			track_ok = False
	track['track_bytes'] = track_bytes
	return track

def decode_62(encoded_data):
	'''Decode 6+2 encoded nibbles in a standard sector of 16'''
	checksum = 0
	secondary = []
	decoded_data = []
	# first 86 bytes represent the lower two bits of the next 256 bytes
	for offset in range(86):
		checksum ^= translate_62(encoded_data[offset])
		secondary.append(checksum)
	# reverse them, we need them in the other order
	secondary = secondary[::-1]
	# next 256 bytes represent the high bits
	for offset in range(256):
		checksum ^= translate_62(encoded_data[offset + 86])
		decoded_data.append(checksum << 2)
	# decode was successful if checksum plus XOR the last byte is zero, stored in element 256
	decoded_data.append(translate_62(encoded_data[342]) ^ checksum)
	# reassemble the bytes
	for offset in range(86):
		lo = secondary[85 - offset]
		decoded_data[offset] += (((lo & 0b000001) << 1) + ((lo & 0b000010) >> 1))
		decoded_data[offset + 86] += (((lo & 0b000100) >> 1) + ((lo & 0b001000) >> 3))
		if offset < 84:
			decoded_data[offset + 172] += (((lo & 0b010000) >> 3) + ((lo & 0b100000) >> 5))
	return decoded_data

def decode_53(encoded_data):
	'''Decode 5+3 encoded nibbles in a standard sector of 13'''
	# This is pretty hard to follow, puzzled out from the DOS 3.2 source.
	# Beneath Apple DOS was not specific enough to reveal the details.
	# Primary buffer is 256 bytes long, divided into 5 bands of 51 bytes, plus one byte
	# These are the higher bits, so they are shifted up two bits when stored
	# Secondary buffer has the low bits.  Secondary buffer has three 51-byte bands plus one byte.
	# The high three bits in secondary buffer (---xxx--) are the low bits for the first three bytes.
	# The low two bits in secondary buffer (------xx) are the low bits for the next two bytes, spread across bands.
	# Incidentally, this is interesting but a little bit pointless.  This information would be useful
	# for a dsk but dsk generally does not support 13-sectors.  It can help with track length estimation.
	# When written as a dsk, it'll write 13 sectors and 3 zero sectors per track.
	checksum = 0
	secondary = []
	decoded_data = []
	# read the secondary buffer first
	for offset in range(154):
		checksum ^= translate_53(encoded_data[offset])
		secondary.append(checksum)
	# reverse them, we need them in the other order
	secondary = secondary[::-1]
	# read the primary buffer (high bits, rotate left to free the three lower bits)
	for offset in range(256):
		checksum ^= translate_53(encoded_data[offset + 154])
		decoded_data.append(checksum << 3) # I had 2 in a previous version, must have been wrong
	# decode was successful if checksum plus XOR the last byte is zero, stored in element 256
	decoded_data.append(translate_53(encoded_data[410]) ^ checksum)
	# reassemble the bytes
	for offset in range(0x33):
		# Lower bits for first three primary bands are in ---xxx---, rotate into place and add.
		for band in range(3):
			decoded_data[(offset * 5) + band] += (secondary[(band * 0x33) + offset] >> 2)
		# Lower bits for last two primary bands are spread across the three secondary bands
		# I could do this in a two-step loop but it seems more trouble than it is worth.
		lower_bit1 = secondary[(0 * 0x33) + offset] & 2 << 1
		lower_bit2 = secondary[(1 * 0x33) + offset] & 2
		lower_bit3 = secondary[(2 * 0x33) + offset] & 2 >> 1
		decoded_data[(offset * 5) + 3] += (lower_bit1 + lower_bit2 + lower_bit3)
		lower_bit1 = secondary[(0 * 0x33) + offset] & 1 << 2
		lower_bit2 = secondary[(1 * 0x33) + offset] & 1 << 1
		lower_bit3 = secondary[(2 * 0x33) + offset] & 1
		decoded_data[(offset * 5) + 4] += (lower_bit1 + lower_bit2 + lower_bit3)
	# last byte
	decoded_data[255] = (encoded_data[255] << 3) + encoded_data[409]
	return decoded_data

def translate_62(nibble):
	'''Nibble translate table for 6+2 encoding'''
	try:
		translation = {
			0x96: 0x00, 0x97: 0x01, 0x9a: 0x02, 0x9b: 0x03, 0x9d: 0x04, 0x9e: 0x05, 0x9f: 0x06, 0xa6: 0x07,
			0xa7: 0x08, 0xab: 0x09, 0xac: 0x0a, 0xad: 0x0b, 0xae: 0x0c, 0xaf: 0x0d, 0xb2: 0x0e, 0xb3: 0x0f,
			0xb4: 0x10, 0xb5: 0x11, 0xb6: 0x12, 0xb7: 0x13, 0xb9: 0x14, 0xba: 0x15, 0xbb: 0x16, 0xbc: 0x17,
			0xbd: 0x18, 0xbe: 0x19, 0xbf: 0x1a, 0xcb: 0x1b, 0xcd: 0x1c, 0xce: 0x1d, 0xcf: 0x1e, 0xd3: 0x1f,
			0xd6: 0x20, 0xd7: 0x21, 0xd9: 0x22, 0xda: 0x23, 0xdb: 0x24, 0xdc: 0x25, 0xdd: 0x26, 0xde: 0x27,
			0xdf: 0x28, 0xe5: 0x29, 0xe6: 0x2a, 0xe7: 0x2b, 0xe9: 0x2c, 0xea: 0x2d, 0xeb: 0x2e, 0xec: 0x2f,
			0xed: 0x30, 0xee: 0x31, 0xef: 0x32, 0xf2: 0x33, 0xf3: 0x34, 0xf4: 0x35, 0xf5: 0x36, 0xf6: 0x37,
			0xf7: 0x38, 0xf9: 0x39, 0xfa: 0x3a, 0xfb: 0x3b, 0xfc: 0x3c, 0xfd: 0x3d, 0xfe: 0x3e, 0xff: 0x3f,
		}[nibble]
	except:
		# TODO: Invalidate the data block in this situation. Checksum should fail anyway, though.
		translation = 0x00
	return translation

def translate_53(nibble):
	'''Nibble translate table for 5+3 encoding'''
	try:
		translation = {
			0xab: 0x00, 0xad: 0x01, 0xae: 0x02, 0xaf: 0x03, 0xb5: 0x04, 0xb6: 0x05, 0xb7: 0x06, 0xba: 0x07,
			0xbb: 0x08, 0xbd: 0x09, 0xbe: 0x0a, 0xbf: 0x0b, 0xd6: 0x0c, 0xd7: 0x0d, 0xda: 0x0e, 0xdb: 0x0f,
			0xdd: 0x10, 0xde: 0x11, 0xdf: 0x12, 0xea: 0x13, 0xeb: 0x14, 0xed: 0x15, 0xee: 0x16, 0xef: 0x17,
			0xf5: 0x18, 0xf6: 0x19, 0xf7: 0x1a, 0xfa: 0x1b, 0xfb: 0x1c, 0xfd: 0x1d, 0xfe: 0x1e, 0xff: 0x1f,
		}[nibble]
	except:
		# TODO: Invalidate the data block in this situation. Checksum should fail anyway, though.
		translation = 0x00
	return translation

# Check for a fuzzy match between candidate copies of a track.
# This has to be as tight as possible, this is called a lot and can really slow the program down.
# I've done everything I can think of to save cycles and fail as fast as possible
three_ones = bytearray(b'\x01\x01\x01')
def check_match(needlebits, haystackbits):
	'''Check for a match between needlebits and haystackbits'''
	global three_ones
	# This match check will succeed if they match, but also tries to accommodate the random bits
	# that can arise from the Disk II controller
	# First, if they're actually equal then we're done already
	if needlebits == haystackbits:
		return True
	# If the match wasn't exact, we need to scan
	# I am at this point simply making this up, but here is the strategy:
	# A 1 could either be real or a spurious 1.
	# The odds of getting three spurious 1s in a row are low because the gain should be reset.
	# NOTE: I'm not sure about this.  It might be that even spurious 1s can come in longer streams
	# if the gain is not reset.  And I'm not sure why it would be, come to think of it.
	# This is a truly hard problem.
	# I think the *zeros* can be trusted perhaps more than the ones. Maybe that's what I should be
	# doing, scanning and failing if the zeros don't line up.
	# Wait, no, that doesn't make any sense.  A zero could be lined up with a spurious 1.
	# Maybe I just need a simple threshold for failure.  Give up if failure exceeds 10% or sutin.
	# So two bitstrings match if for every 111 in one we have **1 in the other.
	# This scans for 111s, and bails out with a failed match if the other contains **0.
	# This does not account for "slippage" -- can't recover from an extra bit in one stream
	# If we make it all the way through, we matched
	# matched = True
	# for offset in range(3, len(needlebits)):
	score = 50 # five bits for free
	for offset in range(0, len(needlebits)):
		# alt_offset = offset - 1
		# check_begin = offset - 3
		# if needlebits[check_begin: offset] == three_ones and haystackbits[alt_offset] == 0:
		# 	matched = False
		# 	break
		# if haystackbits[check_begin: offset] == three_ones and needlebits[alt_offset] == 0:
		if haystackbits[offset] == needlebits[offset]:
			score += 1
		else:
			if score <= 20:
				# matched = False
				break
			score -= 20
	return (score > 20)

def find_sync(track):
	'''Find regions of sync bits on a track'''
	global options
	# A syncing region is essentially defined by a series of FFs from the sequencer.
	# We should already have this information from the nibbles
	# So, whether standard sectors were sought or not, I can still look for streams of FFs.
	# The assumption made here (not entirely valid) is that the longest sync stream will be
	# at the end of a track. 
	# Note, though, I don't think FF is the only nibble that can be used to sync, and I
	# suspect that some track arcing schemes may not use sync on each track
	# (that is, they can sync on one track and then arc into another maintaining sync)
	runs_sequential = []
	current_run = 0
	nibbles = track['nibbles']
	nits = track['nits']
	offsets = track['offsets']
	for offset in range(len(nibbles)):
		# FF sync will obviously have slurped up more than 8 bits, usually 10.
		if nibbles[offset] == 255 and nits[offset] > 8:
			current_run += 1
		else:
			# There is no such thing as a run of fewer than 5 sync nibbles, I call.
			if current_run > 4:
				runs_sequential.append([current_run, offsets[offset], offset])
			current_run = 0
	# sort runs by size so we can find the top two
	runs = sorted(runs_sequential, key=lambda run: run[0], reverse=True)
	track['sync_runs_sequential'] = runs_sequential
	track['sync_runs'] = runs
	if options['werbose']:
		message('Sync spans found, in decreasing lengths:', 2)
		prev_nib_offset = 0
		prev_bit_offset = 0
		prev_run = 999999
		columns = 0
		for run in runs:
			if prev_run > run[0]:
				message('', 2)
				message('{:4d}: '.format(run[0]), 2, end='')
			message('{:5d} {:5d} {:6d} {:6d} / '.format(\
				run[2], \
				abs(run[2]-prev_nib_offset) if run[0] == prev_run else 0, \
				run[1], \
				abs(run[1]-prev_bit_offset) if run[0] == prev_run else 0 \
				), 2, end='')
			columns += 1
			if columns > 3:
				columns = 0
				message('' , 2)
				message('      ', 2, end='')
			prev_nib_offset = run[2]
			prev_bit_offset = run[1]
			prev_run = run[0]
		message('', 2)
	# top two will almost certainly be exactly a track apart
	# if of the usual sort.  Need to be nearly the same and over 90+ sync nibbles to count here
	# and of course there need to be at least two sync runs, and even less than three is dangerous
	if len(runs) > 1:
		if abs((runs[0])[0] - (runs[1])[0]) < 3 and (runs[0])[0] > 90:
			sync_haystack = (runs[1])[1]
			sync_needle = (runs[0])[1]
			if sync_needle > sync_haystack:
				sync_needle = sync_haystack
				sync_haystack = (runs[0])[1]
			# if the distance is implausibly far, sync may have been caught three times
			if sync_haystack - sync_needle > 52500:
				# so grab the next one down and use that.  There can't be more than three.
				sync_haystack = (runs[2])[1]
				if sync_needle > sync_haystack:
					sync_haystack = sync_needle
					sync_needle = (runs[2])[1]
			# if what we wound up with is plausible, store it
			if 50500 < (sync_haystack - sync_needle) < 52500:
				track['sync_needle'] = sync_needle
				track['sync_haystack'] = sync_haystack
				track['sync_nibstart'] = (runs[0])[2]
				# TODO: Check to be sure I got the first pass nibble start there.
			else:
				message('Track {} implausible sync distance. Needle {}, haystack {}, length {}'.format( \
					track['track_number'], sync_needle, sync_haystack, sync_haystack - sync_needle), 1)
		else:
			message('Track {} no sufficiently long and consistent sync runs to use for track size'.format(track['track_number']), 1)
	else:
		message('Track {} essentially no sync runs to use for track size'.format(track['track_number']), 1)
	return track

def set_track_points_to_sync(track):
	'''Use track sync information to set the needle and haystack values'''
	global options
	global three_ones
	bits = track['bits']
	bit_length = len(bits)
	# A prior computation should have already found the syncs if we got here.
	# I am going to trust these if I found them, only turning to the hard math if necessary.
	# HOWEVER, it is easily possible for these sync regions to be placed such that we don't
	# have two contiguous tracks after the first one.  If first sync is between about 25000
	# and 52000 samples in, we have to back up.
	sync_needle = track['sync_needle']
	sync_haystack = track['sync_haystack']
	# if we have to back up, back up by sync runs until we're in range
	# locate the positions of the major sync boundary in the sync runs list
	sync_offsets = [x[1] for x in track['sync_runs_sequential']]
	sync_needle_index = sync_offsets.index(sync_needle)
	sync_haystack_index = sync_offsets.index(sync_haystack)
	while sync_haystack + 52500 > bit_length:
		message('Haystack sync mark too far forward.  Will retreat.  Needle: {:6d} Haystack: {:6d} Distance: {:6d}'.format(\
			sync_needle, sync_haystack, sync_haystack - sync_needle), 2)
		sync_needle_index -= 1
		# while track['sync_runs_sequential'][sync_needle_index][0] < 7:
		# 	sync_needle_index -= 1
		sync_haystack_index -= 1
		# while track['sync_runs_sequential'][sync_haystack_index][0] < 7:
		# 	sync_haystack_index -= 1
		sync_needle = sync_offsets[sync_needle_index]
		sync_haystack = sync_offsets[sync_haystack_index]
	# Now push forward again to first string of 111 to try to counter spurious 1s
	# for x in range(sync_needle, sync_needle + 2048):
	# 	if bits[x: x+3] == three_ones:
	# 		sync_needle = x
	# 		break
	# for x in range(sync_haystack, sync_haystack + 2048):
	# 	if bits[x: x+3] == three_ones:
	# 		sync_haystack = x
	# 		break
	message('Sync marks now say: Needle: {:6d} Haystack: {:6d} Distance: {:6d}'.format(\
		sync_needle, sync_haystack, sync_haystack - sync_needle), 2)
	# We should have backed up enough by now that a full track is available from both
	# sync_needle and sync_haystack
	# save them as the definitive start points for the track and its second copy
	track['match_needle'] = sync_needle
	track['match_haystack'] = sync_haystack
	track['match_bits'] = 0
	return track	

def find_repeats(track):
	'''Analyze a track to find the repeat points'''
	global options
	global three_ones
	bits = track['bits']
	bit_length = len(bits)
	# This is actually a fairly hard problem because the bit read can be different on each pass
	# If we actually are just going to copy the whole track, then just do that
	if options['no_translation']:
		track['match_needle'] = 9
		track['match_haystack'] = len(bits) - 8
		track['match_bits'] = len(bits) - 8
	elif 'sync_needle' in track:
		# If we found a long region of sync nibbles about a track apart, then
		# use those to define the track size.  The following function will back the
		# pointers up if needed and record the result as match_needle/match_haystack.
		track = set_track_points_to_sync(track)
	else:
		# If we didn't get a good guess from the sync and we're actually cutting the
		# track, then we have to do some further analysis.
		# We'll try a few different needle points to try to get the best read
		# Currently defined as starting at the beginning, advancing by about an
		# eighth of a revolution, up to a half revolution.
		needle_offset = 0
		needle_advance = 6400
		stop_needle = 26000
		# If we did a sector analysis and got something, we will have a predicton about the
		# track size based on the bits that elapse between sector repeats.
		# This should actually be a pretty reliable number, but for the moment I'm just taking
		# it to be the start of the search length.  If it was accurate, we should succeed more or
		# less immediately.
		if 'predicted_track_bits' in track:
			track_minimum = track['predicted_track_bits']
			message('Sector scan predicts repeat at minimum {:d}'.formate(track['predicted_track_bits']), 2)
		else:
			# if we have nothing to go by, pick a lowish but reasonable start length
			track_minimum = 50500
		# don't push the haystack past the point where a whole image is no longer available
		stop_haystack = len(bits) - track_minimum
		# window0 is quick search size
		# window1-3 are sufficient, good, best matches
		# not in an array to save a very small numbers of cycles
		window0 = 1600
		window1 = 3200
		window2 = 12800
		window3 = 25600
		track['match_bits'] = 0
		found_match = False
		track['match_hits'] = [0, 0, 0, 0]
		while needle_offset < stop_needle:
			# Push the needle forward until it's on a sequence of three 1s in a row, within reason.
			# This is to try to avoid spurious bits if possible.
			# Very well could land us in the middle of sync.  Not sure if that's a problem.
			# for x in range(needle_offset, needle_offset + 1024):
			# 	if bits[x: x+3] == three_ones:
			# 		needle_offset = x
			# 		break
			# start the search at what is approximately the minimum length a track might be
			haystack_offset = needle_offset + track_minimum
			# but actually if we're at a point where a whole second sample can no longer be available, bail
			# This would only arise if we've been through the search loop several times.
			if haystack_offset > stop_haystack:
				break
			# prefetch the comparison windows before we get into the loop
			stop0 = needle_offset + window0
			stop1 = needle_offset + window1
			stop2 = needle_offset + window2
			needle0 = bits[needle_offset: stop0]
			needle1 = bits[stop0: stop1]
			needle2 = bits[stop1: stop2]
			needle3 = bits[stop2: needle_offset + window3]
			# don't push the haystack beyond the longest a track could be (I'm guessing an approximation)
			stop_offset = needle_offset + 52500
			while haystack_offset < stop_offset:
				stop0 = haystack_offset + window0
				if check_match(needle0, bits[haystack_offset: stop0]):
					(track['match_hits'])[0] += 1
					stop1 = haystack_offset + window1
					if check_match(needle1, bits[stop0: stop1]):
						(track['match_hits'])[1] += 1
						# We got a match sufficient to call the repeat
						found_match = True
						stop2 = haystack_offset + window2
						if check_match(needle2, bits[stop1: stop2]):
							(track['match_hits'])[2] += 1
							if check_match(needle3, bits[stop2: haystack_offset + window3]):
								(track['match_hits'])[3] += 1
								track['match_bits'] = window3
								track['match_needle'] = needle_offset
								track['match_haystack'] = haystack_offset
								# this is as good as we can hope for, stop looking
								break
							else:
								# if this is a level better than a previous match save this as current best
								if track['match_bits'] < window2:
									track['match_bits'] = window2
									track['match_needle'] = needle_offset
									track['match_haystack'] = haystack_offset
						else:
							# if this is a level better than a previous match save this as current best
							if track['match_bits'] < window1:
								track['match_bits'] = window1
								track['match_needle'] = needle_offset
								track['match_haystack'] = haystack_offset
				haystack_offset += 1
			# we don't look for anything better than the best bitmatch, so if we found one, don't push on
			if (track['match_hits'])[3] > 0:
				break
			needle_offset += needle_advance
		if not found_match:
			# if we still didn't find a match even after pushing the needle, either write the whole thing
			# or treat it as unformatted.  We can't do anything with this track.
			if options['write_full']:
				track['match_needle'] = 0
				track['match_haystack'] = len(bits) - 8
				track['match_bits'] = len(bits) - 8
			elif options['use_slice']:
				track['match_needle'] = 0
				track['match_haystack'] = 51400 # just a guess, best of a bad situation
				track['match_bits'] = 51400
			else:
				track['match_needle'] = 0
				track['match_haystack'] = 0
				track['match_bits'] = 0
		track['match_found'] = found_match
	track['data_bits'] = track['match_haystack'] - track['match_needle']
	# Analyze bit differences and repair the bit stream
	if options['repair_tracks']:
		track = repair_bitstream(track)
		# since this may have changed during the repair, recompute the length
		track['data_bits'] = track['match_haystack'] - track['match_needle']
	# compute the byte information for the bitstream for the fdi file
	# for this I will re-ecode the bytes from the slice of the bitstream
	# If needle was zero, this is in principle identical to what was in the EDD file
	fdi_bytes = bytearray()
	byte_offset = track['match_needle']
	haystack_offset = track['match_haystack']
	if haystack_offset > 0:
		if options['use_second']:
			bits = track['bits'][track['match_haystack']: track['match_haystack'] + track['data_bits']]
		else:
			bits = track['bits'][track['match_needle']: track['match_haystack']]
		fdi_bytes = bits_to_bytes(bits)
	track['fdi_bytes'] = fdi_bytes
	return track

def repair_bitstream(track):
	'''Analyze bit streams and attempt to repair bit slippage'''
	global options
	bits = track['bits']
	# Analyze bit differences and report in werbose mode	
	track_length = track['match_haystack'] - track['match_needle']
	if track_length == 0:
		message('Bit differences not computed, track treated as unformatted.', 2)
	elif track_length > 52500:
		message('Bit differences not computed, track using whole 2.5x read.', 2)
	else:
		message('Comparing track from {} to {} with track from {} to {} length {} of total bits {}'.format(\
			track['match_needle'], track['match_haystack'], track['match_haystack'], \
			track['match_haystack'] + track['data_bits'], track['data_bits'], len(track['bits'])), 1)
		needle_bits = bits[track['match_needle']:track['match_haystack']]
		haystack_bits = bits[track['match_haystack']: track['match_haystack'] + track['data_bits']]
		bit_offset = 0
		perfect_match = True
		verify_size = 4
		previous_offset_issue = 0
		bit_errors = {'needle_slips': 0, 'haystack_slips': 0, 'mismatches': 0}
		while bit_offset < len(needle_bits) - 8:
			proceed = True
			window_end = bit_offset + 8
			needle_window = needle_bits[bit_offset: window_end]
			haystack_window = haystack_bits[bit_offset: window_end]				
			if not (needle_window == haystack_window):
				# there was a mismatch, can we figure out what happened?
				perfect_match = False
				note = '??Bits different'
				needle_byte = bits_to_byte(needle_window)
				haystack_byte = bits_to_byte(haystack_window)
				eor_byte = needle_byte ^ haystack_byte
				double_window = window_end + verify_size
				if double_window < len(needle_bits) and double_window < len(haystack_bits):
					# Only bother proceeding if we're not right at the end and can fix something.
					# Locate the position of the first mismatching bit
					mismatch_index = 0
					while eor_byte < 128:
						eor_byte = eor_byte << 1
						mismatch_index += 1
					# Did needle lose a bit?  Try removing mismatch from haystack and see if this and next byte match now
					needle_patch = needle_bits[bit_offset: double_window - 1]
					haystack_patch = haystack_bits[bit_offset: double_window]
					missing_bit = haystack_patch[mismatch_index]
					needle_patch.insert(mismatch_index, missing_bit)
					if needle_patch == haystack_patch:
						# that solved it, needle lost a bit
						# add it into needle for good
						needle_bits.insert(mismatch_index + bit_offset, missing_bit)
						note = 'Needle lost a bit'
						bit_errors['needle_slips'] += 1
						proceed = False
					else:
						# Did needle lose two bits?
						needle_patch = needle_patch[:-1]
						missing_bit2 = haystack_patch[mismatch_index + 1]
						needle_patch.insert(mismatch_index + 1, missing_bit2)
						if needle_patch == haystack_patch:
							# that solved it, needle lost 2 bits
							# add them into needle for good
							needle_bits.insert(mismatch_index + bit_offset, missing_bit2)
							needle_bits.insert(mismatch_index + bit_offset, missing_bit)
							note = 'Needle lost 2 bits'
							bit_errors['needle_slips'] += 2
							proceed = False
						else:
							# Ok, did haystack lose a bit?
							needle_patch = needle_bits[bit_offset: double_window]
							haystack_patch = haystack_bits[bit_offset: double_window - 1]
							missing_bit = needle_patch[mismatch_index]
							haystack_patch.insert(mismatch_index, missing_bit)
							if needle_patch == haystack_patch:
								# that solved it, haystack lost a bit
								# add it into haystack for good
								haystack_bits.insert(mismatch_index + bit_offset, missing_bit)
								note = 'Haystack lost a bit'
								bit_errors['haystack_slips'] += 1
								proceed = False
							else:
								# ok, did haystack lose two bits?
								haystack_patch = haystack_patch[:-1]
								missing_bit2 = needle_patch[mismatch_index + 1]
								haystack_patch.insert(mismatch_index + 1, missing_bit2)
								if needle_patch == haystack_patch:
									# that solved it, haystack lost a bit
									# add it into haystack for good
									haystack_bits.insert(mismatch_index + bit_offset, missing_bit2)
									haystack_bits.insert(mismatch_index + bit_offset, missing_bit)
									note = 'Haystack lost 2 bits'
									bit_errors['haystack_slips'] += 2
									proceed = False

								else:
									bit_errors['mismatches'] += 1
				# report the mismatch
				message('Offset:{}{:6d} needle: {:08b} haystack: {:08b} EOR: {:08b} Guess: {}'.format(\
					'*' if bit_offset > previous_offset_issue + 8 else ' ', \
					bit_offset, needle_byte, haystack_byte, needle_byte ^ haystack_byte, note
					), 2)
				previous_offset_issue = bit_offset
				# TODO: Do something with this repaired track information when writing the real track
			if proceed:
				bit_offset += 8
		if perfect_match:
			message('No bit differences found.', 1)
		else:
			# There are some repairs we can do.
			# If we got here, we are assuming that we want to do the repairs, won't have been called otherwise.
			# This is destructive, overwrites the bits with new improved slippage-free bits
			# TODO: Collect the information we have about weak bits, MFI can store those
			track['bits'][track['match_haystack']: track['match_haystack'] + track['data_bits']] = haystack_bits
			track['bits'][track['match_needle']:track['match_haystack']] = needle_bits
			track['match_bits'] = len(needle_bits)
			track['match_haystack'] = track['match_needle'] + track['match_bits']
			message('Bit stream repaired (slips: {} needle, {} haystack, mismatches: {}), now needle {}, haystack {}, length {}.'.format(\
				bit_errors['needle_slips'], bit_errors['haystack_slips'], bit_errors['mismatches'], \
				track['match_needle'], track['match_haystack'], track['match_bits']), 1)
	return track

def bits_to_bytes(bits):
	bit_offset = 0
	bytes = bytearray()
	bits.extend([0, 0, 0, 0, 0, 0, 0, 0])
	for bit_offset in range(0, len(bits), 8):
		bytes.append(bits_to_byte(bits[bit_offset: bit_offset + 8]))
	return bytes

def bits_to_byte(bits):
	byte = 0
	for bit in bits:
		byte = byte << 1
		if bit == 1:
			byte += 1
	return byte	

if __name__ == "__main__":
	sys.exit(main())