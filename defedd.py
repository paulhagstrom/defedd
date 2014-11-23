#!/usr/bin/env python3

import sys
import zlib
import getopt
import struct
import math
import time

# defedd - converter/analyzer for EDD files (disk images produced by I'm fEDD Up, Brutal Deluxe)
# Paul Hagstrom, started August 2014
# First attempt at using Python, so brace yourself for the occasional non-Pythonic dumbness.
# TODO: I have not been very good at making this readable by anyone but me, or even by me-at-a-distance.
# TODO: Need to refresh current state up here.  This is out of date.
# TODO: Consider whether .dsk is a good target at all, vs. .do (to make explicit the ordering)
# TODO: Handle d13 13-sector images, and figure out what emulators support them.  (Though I think it may be none.)
# In its current state I haven't gotten it to write mfi successfully yet.
# Recent update to mfi spec may be relevant, can now do quarter tracks.
# Not entirely reliable at finding track divisions, this is probably where all the errors are.
# Tries to "repair" bit slips by comparing two samples of a track, might be unwise.
# Doesn't really work.  Kind of in a half done state at the moment.
# Bit matches not really working very well, looks very likely that each read is different.
# Some testing notes for things that might be ueful:
# Snack Attack parm guides just give deprotection info (CLC in nibble check I think).
# Wizardry is supposed to have boot disk write protected. Tracks A-E are crucial for counting.
# Copts and Robbers: 0 addr DDAADA data MAX=25? sync; 1.5-13/15.5 by 1 sync
# Choplifter complex: 0, 1-8, 9, A-B, C-1E.5 by .5, 20 CII+


# options will be stored globally for retrievability
options = {'write_protect': False, 
		'process_quarters': True, 'process_halves': True, 'analyze_sectors': True, 
		'verbose': False, 'werbose': False, 'console': [sys.stdout], 'write_log': False,
		'write_full': False, 'no_translation': False, 'analyze_bits': True, 'analyze_nibbles': True,
		'repair_tracks': True, 'use_second': False,
		'use_slice': False, 'from_zero': False, 'spiral': False,
		'output_basename': 'outputfilename',
		'output': {'nib': False, 'dsk': False, 'mfi': False, 'fdi': False, 'po': False, 'v2d': False, 'nit': False}
		}

def main(argv=None):
	'''Main entry point'''
	global options

	print("defedd - analyze and convert EDD files.")

	try:
		opts, args = getopt.getopt(sys.argv[1:], "hndfmp5txl1qcak20srvw", \
			["help", "nib", "dsk", "fdi", "mfi", "po", "v2d", "nit", "protect", "log",
				"int", "quick", "cheat", "all", "keep", "second", "zero", "slice", "spiral",
				"verbose", "werbose"])
	except getopt.GetoptError as err:
		print(str(err))
		usage()
		return 1

	try:
		eddfilename = args[0]
	except:
		print('You need to provide the name of an EDD file to begin.')
		return 1

	for o, a in opts:
		if o == "-h":
			usage()
			return 0
		# output file type options
		elif o == "-f" or o == "--fdi":
			options['output']['fdi'] = write_fdi_file
			# options['output']['fdi'] = eddfilename + ".fdi"
			print("Will save fdi file.")
		elif o == "-m" or o == "--mfi":
			options['output']['mfi'] = write_mfi_file
			print("Will save mfi file.")
		elif o == "-5" or o == "--v2d":
			options['output']['v2d'] = write_v2d_file
			print("Will save v2d/d5ni file.")
		elif o == "-n" or o == "--nib":
			options['output']['nib'] = write_nib_file
			print("Will save nib file.")
		# elif o == "-t" or o == "--nit":
		# 	options['output']['nit'] = write_nit_file
		# 	print("Will save nit (nibble timing) file.")
		elif o == "-d" or o == "--dsk":
			options['output']['dsk'] = write_dsk_file
			print("Will save dsk file (DOS 3.3 order, a.k.a. .do).")
		# elif o == "-p" or o == "--po":
		# 	options['output']['po'] = write_po_file
		# 	print("Will save ProDOS-ordered po (dsk-like) file.")
		elif o == "-l" or o == "--log":
			options['write_log'] = True
			print("Will save log file.")
		# other options
		elif o == "-x" or o == "--protect":
			options['write_protect'] = True
			print("Will write image as write-protected if supported (FDI)")
		elif o == "-1" or o == "--int":
			options['process_quarters'] = False
			options['process_halves'] = False
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
		elif o == "-r" or o == "--spiral":
			options['spiral'] = True
			print("Will write EDD bits starting from a spiraling start.")
		elif o == "-s" or o == "--slice":
			options['use_slice'] = True
			print("Will write track-length bits starting from beginning of EDD sample for unparseable tracks")
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

	options['output_basename'] = eddfilename

	# Do some sanity checking
	# To write dsk files we need to do the sector analysis, for others it is not needed
	if options['output']['dsk'] and not options['analyze_sectors']:
		print('It is necessary to analyze sectors in order to write a .dsk file, turning that option on.')
		options['analyze_sectors'] = True
	# To write pure EDD->fdi files (which OpenEmulator can handle), we don't need to do any analysis.
	# If user picked no translation but picked something other than fdi, turn no translation off
	if options['no_translation']:
		options['analyze_bits'] = False
		options['analyze_nibbles'] = False
		for output_file in options['output'].items():
			if output_file[1] and output_file[0] != 'fdi':
				print('No translation is only valid for fdi, but since you picked a different output format, analysis is still needed.')
				options['analyze_bits'] = True
				options['analyze_nibbles'] = True
				break

	# TODO: Improve the style of the quarter/half/whole track decisionmaking here
	if options['process_quarters'] and not options['output']['mfi'] and not options['output']['fdi']:
		options['process_quarters'] = False
		if options['process_halves'] and not options['output']['v2d']:
			print('Only processing whole tracks, no sense in processing quarter tracks unless they will be stored.')
			options['process_halves'] = False
		else:
			print('Only processing half tracks, no sense in processing quarter tracks unless they will be stored.')
	# I think I am going to remove the po option for now until I settle the analysis portion
	# if options['output']['dsk'] and options['output']['po']:
	# 	options['output']['po'] = False
	# 	print('Writing dsk and po are mutually exclusive, will write dsk and not po.')
	# TODO: Maybe there is other sanity checking to do here, add if it occurs to me

	# Main analysis loop.  This goes through the whole EDD file track by track and analyzes each track.
	# The resulting analyzed data is all accumulated in memory, then written back out in as many formats as requested.
	
	with open(eddfilename, mode="rb") as eddfile:
		if options['write_log']:
			options['console'].append(open(options['logfilename'], mode="w"))
		tracks = []
		current_track = 0.0
		# this is the length we will use when we need to just guess bit length of a track
		# as soon as a more credible length is found, it will be superseded
		track_length_guess = 51500
		# Loop through the tracks
		while True:
			# Keep track of how long the track takes, helpful (to me) in trying to tighten the analysis loops
			track_start_clock = time.clock()
			eddbuffer = eddfile.read(16384)
			# Keep going so long as we haven't run off the end of the file.
			if eddbuffer:
				# Skip over this data if it's not a whole track and only care about whole tracks
				phase = (4 * current_track) % 4
				if phase == 0 or options['process_quarters'] or (phase == 2 and options['process_halves']):
					# track is the data structure we are storing all the accumulated information in.
					track = {'track_number': current_track}
					# FDI format wants the offset of the index pulse in the bit stream
					# I'll store it in the track data in case I ever want to change it or if some other format wants it
					track['index_offset'] = 0 # bit position of the index pulse
					# convert EDD bytes into an actual bit stream
					track['bits'] = bytes_to_bits(eddbuffer)
					# Analyze the bits unless we're just going to dump them into a raw FDI file
					if options['analyze_bits']:
						# First order of business is to try to eliminate double-sampled bits in the EDD stream
						track = clean_bits(track)
					if options['analyze_nibbles']:
						# Now we want to nibblize the track
						# This will give us the sync bits as well
						# This part is not optional, but it seemed sensible to do the cleaning first.
						# At this point, we may well not have a good handle on where the track begins and ends.
						# We will do a second fairly exhaustive search using two nibblizing heads to see if we
						# can get the nibbles to match.  If the bits matched well, this will go quickly.
						# If the bits didn't match well, perhaps the nibbles will match better.
						# The last act of this routine is to grab the nibbles from the whole track synced with best match
						# If we want to skip the nibble search and just do the whole track, pass False as second parameter.
						track = nibblize(track)
						# It is still conceivable that we don't have a perfect handle on the track
						# if we didn't find a perfect bit or nibble match.  We can try analyzing the sync regions.
						# Right now this just looks at the longest three and sees if they end a plausible track distance apart.
						track = analyze_sync(track)
						# Analyze track for standard 13/16 formats
						# This can be turned off as an option if we know that the disk has no relevant sectors
						if options['analyze_sectors']:
							track = consolidate_sectors(locate_sectors(track))
					# And now we're just going to have to evaluate what we got, do the best we can.
					# Set up the track bits
					# If we got perfect or good bit match, use that
					# Defining good is tricky.  I'll put it at 20% for now.
					if 'bit_match' in track and (track['bit_match'] or track['bit_progress'] > 10000):
						track['track_start'] = track['bit_needle']
						track['track_repeat'] = track['bit_haystack']
						track_length_guess = track['bit_haystack'] - track['bit_needle']
					else:
						# not such a great bit match, sector seek is probably next most reliable
						if 'sector_track_bits' in track:
							track['track_start'] = track['sector_first_offset']
							track['track_repeat'] = track['track_start'] + track['sector_track_bits']
							track_length_guess = track['bit_haystack'] - track['bit_needle']
						else:
							# if sectors did not work fall back to sync if we can
							if 'sync_start' in track:
								track['track_start'] = track['sync_start']
								track['track_repeat'] = track['sync_repeat']
								# not sure this is even reliable enough to use
								# track_length_guess = track['bit_haystack'] - track['bit_needle']
							else:
								# if nothing got us a good track cut, then we treat it as unformatted
								# picking arbitrary numbers here.
								track['track_start'] = 0
								track['track_repeat'] = track_length_guess
					if options['spiral']:
						# advance about a third of turn into the track on each quarter track, an attempt to help sync
						# Testing out on Jawbreaker (spiradisc), didn't work: 17000, 18000, 17250, 17750, 20000, 20006
						# Jawbreaker track zero should be 51091 bits long
						# track zero 17931-separated sync is 20007 bits later on track 0.25 read than on track 0 read.
						# so track .25 should be shifted about 2.55ths of a track back.
						# we have about 6.5 "shifts" of this length worth of bits available.
						# so we shift up 20007 each time, but on the third shift, we subtract out 51091
						# so we can shift 20007, 40014, 60021, 80028, 100035
						# or 20007, 400014, 8930, 28937, 48944, 17860
						# this is 20007*track - length*int(track/3)
						# mathematically, the following works, but Jawbreaker doesn't boot.
						quarter_track_number = int(4 * track['track_number'])
						track_length = 51091
						advance = 20007 * quarter_track_number - track_length*int(quarter_track_number/3)
						message('advance is {}'.format(advance), 0)
					else:
						advance = 0
					track['track_bits'] = track['bits'][track['track_start'] + advance: track['track_repeat'] + advance]
					# TODO: Test for use_second, write_full, from_zero, spiral here
					# Nibbles should already be set up by the nibblizer, no decisions to make.
					track['processing_time'] = time.clock() - track_start_clock
					track_status(track)
					tracks.append(track)
			else:
				break
			# This does not even consider the possibility that the EDD file is not at quarter track resolution.
			# Maybe someday this can be a parameter, but I'll get it working on quarter tracks first.
			current_track += 0.25

		for output_type, output_file in options['output'].items():
			if output_file:
				output_file(eddfile, tracks)

		# close the log file if we were writing to it
		if options['write_log']:
			(options['console'])[1].close
	return 1

def track_status(track):
	'''Display information about track analysis'''
	global options
	trk = "{:5.2f}:".format(track['track_number'])
	bit_length = track['track_repeat'] - track['track_start']
	if options['no_translation']:
		bits = " No translation, sending all {:5d} bits to fdi file.".format(len(track['bits']))
	else:
		bits = " {:6d} trackbits".format(bit_length)
		bits += " {:6d} bits matched".format(track['bit_progress']) #if 'bit_progress' in track else ''
	sectors = " {:2d} sectors".format(len(track['all_sectors'])) if 'all_sectors' in track else ''
	needle = " {:5d} start".format(track['track_start'])
	proc = " {:5.2f}s".format(track['processing_time'])
	message(trk + bits + sectors + needle + proc)

# A message sent at level 0 (default) is always displayed
# level 1 is displayed in verbose mode, level 2 is displayed in werbose mode
# Any messages go both to the screen and the log file if the log file is requested
def message(message, level=0, end='\n'):
	'''Output messages to the screen and to the log file if requested'''
	global options
	if level == 0 or (level == 1 and options['verbose']) or (level == 2 and options['werbose']):
		for output in options['console']:
			print(message, file=output, end=end)

def usage():
	'''Display help information'''
	print('''
Usage: defedd.py [options] eddfile

Assumption is that the EDD file was produced by I'm fEDD Up.
Quarter tracks.

Options:
Output formats:
 -d, --dsk     Write .dsk file (data-only 16-sector standard images)
 -p, --po      Write .po file (data-only, 16-sector ProDOS ordered images)
 -n, --nib     Write .nib file (for 13-sectors and light protection)
 -t, --nit     Write .nit file (for debugging / checking against I'm fEDD Up)
 -m, --mfi     Write .mfi file (MESS Floppy image simulated flux image)
 -f, --fdi     Write .fdi file (bitstream, cheated images ok in OpenEmulator)
 -5, --v2d     Write .v2d file (D5NI, half tracked nibbles, ok in Virtual II/STM)
 -l, --log     Write .log file of conversion output
 -x, --protect Write protect the disk image if supported (fdi)
Analysis options:
 -z, --nibscan Use double nibble scan to find track
 -q, --quick   Skip standard sector analysis, ok for fdi/mfi/nib
 -1, --int     Consider only whole tracks (not quarter tracks)
 -c, --cheat   Write full 2.5x bit read for unparseable tracks (vs. unformatted)
 -a, --all     Write full 2.5x bit read for all tracks (i.e. cheat everywhere)
 -s, --slice   Write EDD bits to track length for unparseable tracks (cheat lite)
 -0, --zero    Write EDD bits from 0 instead of found track (slice for formatted)
 -r, --spiral  Write EDD bits in 17000-bit spiral to try to keep track sync
 -k, --keep    Do not attempt to repair bitstream
 -2, --second  Use second track repeat if choice is needed (default is first)
Help and debugging:
 -h, --help    You're looking at it.
 -v, --verbose Be more verbose than usual
 -w, --werbose Be way, way (ponponpon) more verbose than usual (implies -v)

 Examples:
 defedd.py -d eddfile.edd (write a dsk file, standard 16-sector format)
 defedd.py -faq eddfile.edd (write an fdi file for OpenEmulator with all 2.5x samples)
 	(works for Choplifter)
 defedd.py -qv eddfile.edd (write a v2d file for Virtual II)
 	(works for standard disks so far)
 defedd.py -qn eddfile.edd (write a nib file, skip sector analysis)
 	(works for 16-sector disks, not stress tested yet)
 defedd.py -fk eddfile.edd (write small fdi file for OE, don't fix bit slips)
 	(works for ... nothing much yet)
 defedd.py -f eddfile.edd (write a one-revolution fdi file for OE with analysis)
 	(works for simple 16-sector disks)
 defedd.py -mk eddfile.edd (write an mfi file for MESS, with analysis, no repairs)
 	(does not work yet)
 	''')
	return

def bytes_to_bits(eddbuffer):
	'''Convert bytes into component bits'''
	bits = bytearray()
	offset = 0
	for byte in eddbuffer:
		binbyte = bin(byte)[2:] # cuts off the 0x from the beginning
		bytebits = [int(bit) for bit in ('00000000'[len(binbyte):] + binbyte)]
		bits.extend(bytebits)
	return bits

def grab_nibble(bits):
	'''Take the first nibble off the bit stream that was passed in'''
	offset = 0
	leading_zeros = 0
	data_register = 0
	wait_for_one = True
	stop_offset = len(bits)-1
	while offset < stop_offset:
		bit = bits[offset]
		if bit == 1:
			data_register = (data_register << 1) + 1
			wait_for_one = False
		else:
			if wait_for_one:
				leading_zeros += 1
			else:
				data_register = data_register << 1
		if data_register > 127:
			# nibble complete return it
			break
		offset += 1
	# if we run out of data, return what we had, though it is probably useless to do so.	
	return {'nibble': data_register, 'leading_zeros': leading_zeros, 'offset': offset}

# This pushes the head ahead past the sync nibbles to reach a synced nibble.
# My first attempt was to just look for the first short nibble after some long ones.
# That's no good because sync nibbles are not guaranteed to read as long unless we
# are already in sync.  What I need to do instead is look for a long nibble, then a
# series of short nibbles.  I will have succeeded if I get a long nibble and then
# several short ones, and I'll return the last long one (likely D5).
# This may not work perfectly on weirdly formatted disks, but they need to be in sync
# too, no?  I guess I worry about spirals, syncing on one track and then moving to another.
# Would also be possible to get in sync by using (more) 9-bit nibbles instead of 10-bit nibbles.
# This will fail to see those.  Probably should add some verbosity to see what it actually finds.
def grab_first_post_sync_nibble(bits):
	'''Search bits for at least two long nibbles and return the last one'''
	offset = 0
	long_nibbles_found = 0
	short_nibbles_found = 0
	while offset < len(bits):
		nibble = grab_nibble(bits[offset:])
		if nibble['leading_zeros'] > 0:
			# this is a long nibble
			long_nibbles_found += 1
			# message('10-bit nibble number {}.'.format(long_nibbles_found), 2)
			# reset the short nibbles count
			short_nibbles_found = 0
			# and remember the last long nibble, that is what we are going to return
			# (because it is really the end of the sync span)
			# offset here where we start looking, nibble[offset] is where that nibble ended.
			# we are returning where the nibble starts
			last_long_nibble = {'offset': offset, 'nibble': nibble}
		# elif nibble['leading_zeros'] == 1:
		# 	# if the "long nibble" only has one timing bit leading into it
		# 	# it is not a real sync nibble
		# 	# reset everything and try again
		# 	# message('Resetting at a 9-bit nibble.', 2)
		# 	long_nibble_founds = 0
		# 	short_nibbles_found = 0
		else:
			# this is a short nibble
			# have we already hit enough long nibbles?
			if long_nibbles_found > 2:
				# yes, have we found enough short nibbles?
				short_nibbles_found += 1
				if short_nibbles_found > 6:
					# yep, we've got enough.  So return the last long nibble we found
					return last_long_nibble
		offset += nibble['offset'] + 1
	# if we get to here we failed to find two long nibbles and a short one.
	message('Could not find even a single long nibble followed by a series of short ones!', 2)
	return False

# Nibblize the bit stream in two different positions in sync, to find the highest rate
# of nibble match.  Also keeps track of timing bits.  Will finish by creating nibble stream
# of entire track (or possibly entire track starting from beginning of best match).
# To avoid the search part and just go with the whole track, pass False as second paramter
# TODO: The odds are good that the nibbles at the beginning will be out of sync.
# See if I can maybe start the nibble check once they are in sync by waiting for two long nibbles first.
# YOU ARE HERE
def nibblize(track, do_search = True):
	'''Run two heads over the bitstream to try to find consistent nibbles'''
	bits = track['bits']
	# We might have a guess from the bit analysis about where the track is.
	needle_offset = track['bit_needle'] if 'bit_needle' in track else 0
	haystack_start = track['bit_haystack'] if 'bit_haystack' in track else 49000
	best = {'ok': False, 'needle': needle_offset, 'haystack': haystack_start, 'nibbles': []}
	if do_search:
		# align the needle to a post-sync nibble
		nibble = grab_first_post_sync_nibble(bits)
		# message('Grab first post sync nibble returned {}'.format(nibble), 2)
		if nibble:
			needle_offset += nibble['offset']
			message('Needle offset moved to {}'.format(needle_offset), 2)
		nibbles = []
		found_match = False
		nibbles_collected = 0
		needle_head = 0
		haystack_head = 0
		track_maximum = 52500
		if needle_offset + (2 * track_maximum) > len(bits):
			haystack_stop = len(bits) - track_maximum
		else:
			haystack_stop = needle_offset + track_maximum
		needle_increment = 2500
		needle_stop = 52500
		haystack_offset = haystack_start
		while True:
			# find the next nibble under the needle head
			needle_bits = bits[needle_offset + needle_head:]
			needle_nibble = grab_nibble(needle_bits)
			# get the next nibble under the haystack head to see if it matches
			haystack_bits = bits[haystack_offset + haystack_head:]
			haystack_nibble = grab_nibble(haystack_bits)
			# message('Check at needle {} got {:2x}({}) and haystack {} got {:2x}({})'.format(\
			# 	needle_offset+needle_head, needle_nibble['nibble'], needle_nibble['offset'], \
			# 	haystack_offset+haystack_head, haystack_nibble['nibble'], haystack_nibble['offset']), 2)
			if needle_nibble['nibble'] != haystack_nibble['nibble']:
				# they don't match
				# was this a better run than current best?
				if len(nibbles) > len(best['nibbles']):
					# yes, record it
					best = {'ok': False, 'needle': needle_offset, 'haystack': haystack_offset, 'nibbles': nibbles}
					message('Current best: {:4d} nibbles, needle {:5d}, haystack {:5d}'.format(len(nibbles), needle_offset, haystack_offset), 2)
				# reset state for the next search iteration
				needle_head = 0
				haystack_head = 0
				nibbles = []
				haystack_offset += 1
				if haystack_offset < haystack_stop:
					continue
				else:
					# we've run off the end with the haystack, so try advancing the needle
					needle_offset += needle_increment
					message('Nibble needle pushed forward, to {:5d}.'.format(needle_offset), 2)
					# align the needle to a post-sync nibble
					nibble = grab_first_post_sync_nibble(bits[needle_offset:])
					# message('Grab first post sync nibble returned {}'.format(nibble), 2)
					if nibble:
						needle_offset += nibble['offset']
						message('Needle offset moved past timing bits to {}.'.format(needle_offset), 2)
					if needle_offset < needle_stop:
						haystack_offset = haystack_start + needle_offset
						if needle_offset + (2 * track_maximum) > len(bits):
							haystack_stop = len(bits) - track_maximum
						else:
							haystack_stop = needle_offset + track_maximum
						continue
					else:
						# we've run off the end of the needle as well
						break
			# they do match, collect them
			nibbles.append(needle_nibble)
			needle_head += needle_nibble['offset'] + 1
			haystack_head += haystack_nibble['offset'] + 1
			if needle_head + needle_offset > haystack_offset:
				# we just crossed over into the haystack
				# we have completely succeeded
				best = {'ok': True, 'needle': needle_offset, 'haystack': haystack_offset, 'nibbles': nibbles}
				message('Total match: {:4d} nibbles, needle {:5d}, haystack {:5d}'.format(len(nibbles), needle_offset, haystack_offset), 2)
				break
	# We are done and have a best match of some sort by now (unless we skipped the search, at least).
	# Last thing is to nibblize the whole track (in case we didn't get a total match)
	# This can be slightly better than just nibblizing it from the outset because since we know where our best match
	# is, we can at least align the nibbles by starting at the best match needle
	# So I will discard all nibbles before that.  Evaluation of wisdom of this move pending.
	offset = best['needle']
	track_nibbles = bytearray()
	track_timing = []
	nibble_offsets = []
	sync_regions = []
	sync_start = 0
	sync_run = 0
	message('Doing full track nibblize and collecting timing bits.', 2)
	message('Starting offset at {:5d}, will record track nibbles at {:5d}'.format(offset, best['haystack']), 2)
	while offset < len(track['bits']):
		nibble = grab_nibble(track['bits'][offset:])
		track_nibbles.append(nibble['nibble'])
		track_timing.append(nibble['leading_zeros'])
		nibble_offsets.append(nibble['offset'])
		if offset < best['needle'] + 64 or (offset > best['haystack'] - 32 and offset < best['haystack'] + 64):
			message('Nibble: {:2x} with timing {:2d} at offset {:5d}'.format(nibble['nibble'], nibble['leading_zeros'], offset), 2)
		if nibble['leading_zeros'] > 0:
			# this was a long nibble, a sync byte or something more devious.
			# if it's the first one, start recording this as a region
			if sync_start == 0:
				sync_start = offset
				sync_run = 0
			else:
				# and if it is continuing in a region we already opened, keep track of the number of nibbles
				sync_run += 1
		else:
			# this is a regular sized nibble, but if we were recording a sync region, close it
			# offset in the sync regions list is the offset of the beginning of the first long nibble
			if sync_start > 0:
				sync_regions.append([sync_run, sync_start, offset])
				sync_start = 0
				sync_run = 0
		offset += nibble['offset'] + 1
		# Since we're grabbing the whole track here starting at needle, notice when we've got the best track nibbles
		# It is >= rather than == because there's a chance we had no best match at all.
		if offset >= best['haystack'] and not 'track_nibbles' in track:
			track['track_nibbles'] = track_nibbles[:] # freeze it in time, don't equate the pointers
			# message('Track nibbles stored, there are {:5d} of them'.format(len(track['track_nibbles'])), 2)
	track['nibble_best'] = best
	track['all_nibbles'] = track_nibbles
	track['all_timing'] = track_timing
	track['all_offsets'] = nibble_offsets
	track['sync_regions'] = sync_regions
	message('Nibbles collected. Track_nibbles is {} long.'.format(len(track['track_nibbles'])), 2)
	message('All_nibbles is {} long.'.format(len(track['all_nibbles'])), 2)
	# message('First few nibbles of all_nibbles: {}'.format(track_nibbles[:10]), 2)
	# message('First few nibbles of track_nibbles: {}'.format(track['track_nibbles'][:10]), 2)
	# message('Last few nibbles of track_nibbles: {}'.format(track['track_nibbles'][len(track['track_nibbles'])-10:]), 2)
	# message('Nibbles in all_nibbles around end of track_nibbles: {}'.format(track_nibbles[len(track['track_nibbles'])-5: len(track['track_nibbles'])+5]), 2)
	# Just a track's worth of nibbles
	# track['track_nibbles'] = track_nibbles[0:(best['haystack']-best['needle'])]
	# And then just 6656 nibbles for standard .nib format
	track['nib_nibbles'] = (track['track_nibbles'] + track['track_nibbles'])[0:6656]
	# message('About to leave nibblize, track nibbles is {} long'.format(len(track['track_nibbles'])), 2)
	return track

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
	message('offset ADDR: vol track sector 13/16 ; ADDR/DATA: CHK=addr checksum error, ok=addr epilogue ok ', 2)
	# TODO: Keep track of the gaps and optimal beginning of the nibble stream for nib writing.
	# Skip the last 420 nibbles since they cannot contain a sector and this would be their third read anyway
	message('There are {:4d} track nibbles'.format(len(track['track_nibbles'])), 2)
	message('There are {:4d} total nibbles'.format(len(track['all_nibbles'])), 2)
	# message('The first ones are {:2x} {:2x} {:2x}'.format(track['track_nibbles'][0], track['track_nibbles'][1], track['track_nibbles'][2]), 2)
	# tack on the beginning of the track to the end so that we can handle a wrap-around
	scan_nibbles = track['track_nibbles'] + track['track_nibbles'][0:1000]
	scan_nibbles = track['all_nibbles']
	# debug because the track is not lining up
	# message('Comparing repeating track to all nibbles track', 2)
	# message('End of track {}'.format(track['track_nibbles'][-20:]), 2)
	# start_nibbles = track['track_nibbles'][:20]
	# message('Start of track {}'.format(start_nibbles), 2)
	# find_start_offset = len(track['track_nibbles'])
	# while find_start_offset < len(track['all_nibbles'])-20:
	# 	if track['all_nibbles'][find_start_offset:find_start_offset+20] == start_nibbles:
	# 		message('Found start of track at offset {}.'.format(find_start_offset), 2)
	# 		break
	# 	find_start_offset += 1
	# message('All nibbles end+start {}'.format(track['all_nibbles'][len(track['track_nibbles'])-5:len(track['track_nibbles'])+40]), 2)
	stop_scan = len(track['track_nibbles']) + 500 # give it some extra room to loop around, this is at least a (16) sector big.
	stop_scan = len(track['all_nibbles']) - 500 # no, try everything but leave out the last chunk of nibbles
	offset = 0
	awaiting_data = False
	# We will keep track of the gaps between found elements, might be useful at least informationally.
	gap = bytearray()
	while offset < stop_scan:
		nibfield = (scan_nibbles)[offset : offset + 14]
		# message('Looking for {} in {}'.format(bytearray(b'\xd5\xaa\x96'), nibfield), 2)
		if nibfield[0:3] in [bytearray(b'\xd5\xaa\x96'), bytearray(b'\xd5\xaa\xb5')]:
			# we found an address mark (d5aa96 for 16-sector, d5aab5 for 13-sector)
			sector = {
			'dos32': (nibfield[2] == 0xb5), # true if it was 13-sector
			'offset': offset,
			'vol': ((nibfield[3] << 1)+1) & nibfield[4], 
			'track': ((nibfield[5] << 1)+1) & nibfield[6], 
			'sector': ((nibfield[7] << 1)+1) & nibfield[8], 
			'addr_checksum': ((nibfield[9] << 1)+1) & nibfield[10],
			'addr_pre_gap': gap,
			'addr_epilogue': nibfield[11:14]
			}
			sector['addr_checksum_ok'] = (sector['addr_checksum'] == (sector['vol'] ^ sector['track'] ^ sector['sector']))
			# epilogue is not always completely written, if we have the first two nibbles it's good enough
			sector['addr_epilogue_ok'] = (sector['addr_epilogue'][0:2] == bytearray(b'\xde\xaa'))
			# but a gold star if all three were written
			sector['addr_epilogue_perfect'] = (sector['addr_epilogue'][0:3] == bytearray(b'\xde\xaa\xeb'))
			all_sectors.append(sector)
			gap = bytearray()
			if awaiting_data:
				# If we have gotten two address fields in a row, send a linebreak to the console
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
		elif nibfield[0:3] == bytearray(b'\xd5\xaa\xad'): # data mark (for both standard 13- and 16-sector formats)
			# this is presumed to be the data mark on the last pushed sector
			if awaiting_data:
				sector = all_sectors.pop()
			else:
				# we got a data field without having registered an address field
				sector = zero_sector
				message('{:6d}                                '.format(offset), 2, end='')
			# the next 342 (3.3) or 410 (3.2) nibbles will be encoded data, followed by a checksum and epilogue
			data_length = 411 if sector['dos32'] else 343
			nibfield = scan_nibbles[offset + 3: offset + data_length + 6]
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
			# Keep track of the nibbles in the gap between marks we find
			gap.append(scan_nibbles[offset])
			offset += 1
	track['all_sectors'] = all_sectors
	if awaiting_data:
		# if we ended after an address without data, print a linebreak to the console
		message('', 2)
	return track

def dos_order(logical_sector):
	'''DOS 3.3 sector skewing'''
	return {
		0x00: 0x00, 0x01: 0x0d, 0x02: 0x0b, 0x03: 0x09, 0x04: 0x07, 0x05: 0x05, 0x06: 0x03, 0x07: 0x01,
		0x08: 0x0e, 0x09: 0x0c, 0x0a: 0x0a, 0x0b: 0x08, 0x0c: 0x06, 0x0d: 0x04, 0x0e: 0x02, 0x0f: 0x0f,
		}[logical_sector]

def prodos_order(logical_sector):
	'''ProDOS sector skewing'''
	return {
		0x00: 0x00, 0x01: 0x02, 0x02: 0x04, 0x03: 0x06, 0x04: 0x08, 0x05: 0x0a, 0x06: 0x0c, 0x07: 0x0e,
		0x08: 0x01, 0x09: 0x03, 0x0a: 0x05, 0x0b: 0x07, 0x0c: 0x09, 0x0d: 0x0b, 0x0e: 0x0d, 0x0f: 0x0f,
		}[logical_sector]

def cpm_order(logical_sector):
	'''CP/M sector skewing'''
	return {
		0x00: 0x00, 0x01: 0x0c, 0x02: 0x08, 0x03: 0x04, 0x04: 0x0b, 0x05: 0x07, 0x06: 0x03, 0x07: 0x0f,
		0x08: 0x06, 0x09: 0x02, 0x0a: 0x0e, 0x0b: 0x0a, 0x0c: 0x01, 0x0d: 0x0d, 0x0e: 0x09, 0x0f: 0x05,
		}[logical_sector]

def consolidate_sectors(track):
	'''Consolidate all the sectors we found into a standard 13/16 for writing to dsk'''
	global options
	sorted_sectors = {}
	dos32_mode = False
	# prodos_mode = options['write_po']
	if options['werbose']:
		message('Consolidating found sectors by reported sector number and checking data integrity.')
	# collect in an array keyed by self-reported sector number, for all addresses with a proper checksum.
	# also remember the offset of the first sector
	first_offset = 0
	for found_sector in track['all_sectors']:
		if found_sector['addr_checksum_ok']:
			# for now, just saving the sectors that had an ok address checksum.
			# if any sector is in DOS 3.2 mode, presume the whole track is
			# this is actually wildly unsafe, since some early disks can boot in either 13- or 16-sector mode
			if found_sector['dos32']:
				dos32_mode = True
			if first_offset == 0:
				first_offset = found_sector['offset']
			try:
				# keep all copies of the sector that we find, in case we want to compare them
				sorted_sectors[found_sector['sector']].append(found_sector)
			except:
				# didn't have a copy before, this is the first time we found this sector
				sorted_sectors[found_sector['sector']] = [found_sector]
	# look for the bit distance between copies.
	# This will be useful in guessing the track length in the repeat scan.
	# TODO: the results should be basically consistent, but differences could help isolate bit slips
	# However, unlikely to both need to correct bit slips and have identifiable sectors.
	# So it might be interesting to see how reliable the EDD image is, but not much help with protections.
	# Strategy here is to look for the shortest bit distance, but that wasn't based on much thought.
	# Unsure whether longer would be better but if this is just used as the starting point for a search,
	# shortest is best.
	predicted_track_bits = 0
	for sector_number in sorted_sectors.keys():
		base_copy = None
		for copy in sorted_sectors[sector_number]:
			if base_copy:
				# offset is the bit pointer to the end of the nibble where the address mark was found.
				# Since this is just used for distance, that's fine.  If I were using it for a start
				# point in the bit stream, we should subtract 8 from it though.
				bit_distance = ((track['all_offsets'])[copy['offset']] - (track['all_offsets'])[base_copy['offset']])
				# since they should be stacked in ascending order, even if there are three copies
				# of this sector, the closest one should be found first
				# if they vary in bit distance numbers, we want the bigger one
				# so long as it is a sensible track distance
				if 50000 > bit_distance > 53000:
					if bit_distance > predicted_track_bits:
						predicted_track_bits = bit_distance
			else:
				# first copy we find is the one we will compare to
				base_copy = copy
	if predicted_track_bits > 0:
		track['sector_track_bits'] = predicted_track_bits
	track['sector_first_offset'] = first_offset
	# report the results
	# only bother doing this loop if we'll be able to see it (verbose), to save cycles
	if options['verbose'] and len(sorted_sectors) > 0:
		message('After consolidating: (self-id track) DCHK data checksum err, DATA data mismatch err, offset, bit distance twixt copies', 1)
		for sector_number in sorted_sectors.keys():
			data = False
			message('Sec {:0x}: '.format(sector_number), 1, end='')
			for sector in sorted_sectors[sector_number]:
				if data:
					data_match = True if 'data' in sector and sector['data'] == data else False
					bit_distance = sector['offset'] - offset
				else:
					data = sector['data'] if 'data' in sector else False
					bit_distance = 0
					data_match = True
				offset = sector['offset']
				# it is impossible to have a bad address checksum because it wouldn't have been stored
				# message('{} {} {} {:5d} {:5d} /'.format( \
				# 	'    ' if 'addr_checksum_ok' in sector and sector['addr_checksum_ok'] else 'ACHK', \
				message('({:0x}) {} {} {:5d} {:5d} /'.format( \
					sector['track'],
					'    ' if 'data_checksum_ok' in sector and sector['data_checksum_ok'] else 'DCHK', \
					'    ' if data_match else 'DATA', \
					sector['offset'], bit_distance
					), 1, end='')
			message('', 1)
	# Gather the track data for .dsk and .po images, taking the first valid one (data checksum ok) of first two
	dsk_bytes = bytearray()
	track_error = False
	message('Creating the .dsk byte stream for the track.', 2)
	for logical_sector in range(16):
		# TODO: Allow for CP/M, Pascal, ProDOS skewing as well at some point
		if dos32_mode:
			physical_sector = logical_sector
		# elif prodos_mode:
		# 	physical_sector = prodos_order(logical_sector)
		else:
			physical_sector = dos_order(logical_sector)
		try:
			sector = sorted_sectors[physical_sector][0]
			if sector['data_checksum_ok']:
				dsk_bytes.extend(sector['data'])
			else:
				# first sector was not ok, check to see if there's a second sector that is
				try:
					sector = sorted_sectors[physical_sector][1]
					if sector['data_checksum_ok']:
						# second one was ok even though first was not, so store that instead
						dsk_bytes.extend(sector['data'])
					else:
						# append a sector of zeros, neither of the first two were ok
						dsk_bytes.extend(bytearray(256))
						track_error = True
				except:
					# there was no second copy and first was bad, so append a sector of zeros
					dsk_bytes.extend(bytearray(256))
					track_error = True
		except:
			# append a sector of zeros if we did not have this sector recorded
			dsk_bytes.extend(bytearray(256))
			track_error = True
	track['dsk_bytes'] = dsk_bytes
	# For now, just report when there was a bad track, not used anywhere
	if track_error:
		message('At least one sector was bad (and stuffed with zeros).', 2)
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

# This will take the EDD stream, and try to (a) find the point where the track repeats,
# and (b) clean up any double-sampled bits.  Because the EDD file simply reports what the
# head has seen every 32 cycles, if a drive is running at all slow, there is a possibility of getting
# some double-sampled bits.  Obviously it is necessary to find the repeat point in the process if
# we're going to do this cleaning, since it requires comparing two bit streams that are supposed to
# be the same.
# It is my understanding that on the physical media, a zero is indicated by a long steady value and
# a one is indicated by a zero crossing.  Therefore, the most likely event is probably that a spurious
# zero is inserted, less likely that a spurious 1 is inserted.  I will attempt to clean the track using
# this as a heuristic
def clean_bits(track):
	'''Analyze a track to find the repeat points and clean bits when repeat is found'''
	global options
	bits = track['bits'] # the original bits that the EDD card read
	bit_length = len(bits)
	# We'll try a few different needle points to try to get the best read.
	# Since I don't believe this will matter much, only a few different needle tries.
	needle_offset = 0
	needle_advance = 5000
	stop_needle = 52500
	# my observational guesses at the minimum and maximum number of bits a track could have.
	track_minimum = 50500
	track_maximum = 52500
	# don't push the haystack past the point where a whole image is no longer available
	stop_haystack = len(bits) - track_maximum
	best_progress = {'ok': False, 'progress': 0, 'needle_offset': 0, 'haystack_offset': 0, 'bits': {}}
	while needle_offset < stop_needle:
		# start the search at what is approximately the minimum length a track might be
		haystack_offset = needle_offset + track_minimum
		# but actually if we're at a point where a whole second sample can no longer be available, bail
		# This would only arise if we've been through the search loop several times.
		if haystack_offset > stop_haystack:
			break
		# don't push the haystack beyond the longest a track could be
		while haystack_offset < needle_offset + track_maximum:
			repaired_bits = match_surgery(\
				bits[needle_offset: haystack_offset], \
				bits[haystack_offset: haystack_offset + (haystack_offset - needle_offset)])
			if repaired_bits['ok'] or repaired_bits['progress'] > best_progress['progress']:
				best_progress = {'ok': repaired_bits['ok'], 'progress': repaired_bits['progress'], \
					'needle_offset': needle_offset, 'haystack_offset': haystack_offset, 'bits': repaired_bits}
				message('Current best: {:5d} bits, needle {:5d}, haystack {:5d}'.format(best_progress['progress'], needle_offset, haystack_offset), 2)
			if best_progress['ok']:
				# these two spans "completely" matched after surgeries
				break
			haystack_offset += 1
		# if we didn't reach a total match by scanning all the haystack values try pushing the needle a bit and trying again
		# the only obvious circumstance this would help in is if the first 20 bits need surgery on the first pass.
		if best_progress['ok']:
			break
		needle_offset += needle_advance
		message('Bit needle pushed forward, to {:5d}.'.format(needle_offset), 2)
	# We've either got a total match, or done as many total scans as we are going to
	track['bit_match'] = best_progress['ok']
	track['bit_progress'] = best_progress['progress']
	if best_progress['ok']:
		# total match
		message('Found exact copy of bitstream (required {} repairs). {:5d} bits.'.format(\
			len(best_progress['bits']['surgeries']), len(best_progress['bits']['needle'])), 2)
		display_bits('          Bits : ', track['bits'][haystack_offset-20:haystack_offset+20], 2)
		display_bits('    Needle end : ', best_progress['bits']['needle'][-20:], 2)
		display_bits('Haystack start :                     ', best_progress['bits']['haystack'][:20], 2)
		# counterintuitively, we will cut the track down to three copies, since a valid nibble might span the boundary.
		track['bits'] = best_progress['bits']['needle'] + best_progress['bits']['haystack'] + best_progress['bits']['needle']
		track['bit_needle'] = 0
		track['bit_haystack'] = len(best_progress['bits']['needle'])
	else:
		# this was something less than a total match
		if best_progress['progress'] == 0:
			# This was a complete failure, no match at all.  Hard to believe.  Though it does happen.  Unformatted track?
			# Guess we'll just take a wild swinging guess, though it probably won't matter
			message('No bit match could be found at all!', 2)
			track['bit_needle'] = 0
			track['bit_haystack'] = 51500
		else:
			message('Best bit match was {} (required {} repairs)'.format(\
				best_progress['progress'], len(best_progress['bits']['surgeries'])), 2)
			if best_progress['progress'] > 30000:
				# over half the track was a match, so keep the repairs that we did
				# by making the bit stream just the repaired bits
				# This is kind of hazardous, but I hope that the threshold is conservative enough
				message('Bit match was good enough to use for further analysis.', 2)
				track['bits'] = best_progress['bits']['needle'] + best_progress['bits']['haystack'] + best_progress['bits']['needle']
				track['bit_needle'] = 0
				track['bit_haystack'] = len(best_progress['bits']['needle'])
			else:
				# kind of a weak match on the length
				# weak enough that the repairs can't really be trusted, so remember the best
				# needle and haystack pointers, but do not change the official bits
				track['bit_needle'] = best_progress['needle_offset']
				track['bit_haystack'] = best_progress['haystack_offset']
	# Now that we have pinned down where the track boundaries are, do another pass at surgery and collect the track stats
	# Primarily, this is because when we're sizing the track, surgery is only done up to the best match, so a bunch of weak
	# bits would stop the surgery from reaching the end of the track.
	repaired_bits = match_surgery(\
		track['bits'][track['bit_needle']:track['bit_haystack']], \
		track['bits'][track['bit_haystack']: 2*track['bit_haystack'] - track['bit_needle']], True)
	# only bother with this if we will be able to see it
	if options['verbose']:
		message('***** Track structure and repair summary:', 2)
		for msg in [\
				['Spurious 0s in needle:', repaired_bits['surgeries']['needle_zeros']], \
				['Spurious 0s in haystack:', repaired_bits['surgeries']['haystack_zeros']], \
				['Dropped bits in needle:', repaired_bits['surgeries']['needle_drops']], \
				['Dropped bits in haystack:', repaired_bits['surgeries']['haystack_drops']], \
				]:
			message(msg[0], 1, end=' ')
			for offset in msg[1]:
				message('{}'.format(offset), 1, end=' ')
			message('', 1)
		message('Spans of weak bits: ', 1)
		for span in repaired_bits['surgeries']['weak_spans']:
			message('{}-{} '.format(span[0], span[1]), 1)
			# message('{}-{} '.format(span[0], span[1]), 2, end='')
		message('', 1)
	track['repaired_bits'] = repaired_bits
	return track

def match_surgery(needle, haystack, skip_weak = False):
	'''Look for a match between needle and haystack, performing minor surgery if needed'''
	success = False
	surgeries = {'needle_drops': [], 'haystack_drops': [], 'needle_zeros': [], 'haystack_zeros': [], 'weak_spans': []}
	# First check the first 20 bits.  If they don't match, then fail right away
	if needle[0:20] != haystack[0:20]:
		progress = 0
	# If we were already equal from the outset without any surgery, succeed right away
	elif needle == haystack:
		progress = len(needle)
		success = True
	# Otherwise, we need to loop and maybe repair
	else:
		offset = 0
		check_window = 10
		stop_offset = len(needle)
		weak_span_start = -1
		weak_span_closing = 0
		needed_to_close = 30
		while offset < stop_offset:
			if needle[offset] == haystack[offset]:
				# they match.  If we're collecting weak spans and one was open, close it
				if skip_weak and weak_span_start > -1:
					weak_span_closing += 1
					if weak_span_closing > needed_to_close:
						# enough consecutive good bits have come in that we can declare the weak span closed
						surgeries['weak_spans'].append([weak_span_start, offset - weak_span_closing - 1])
						weak_span_start = -1
			else:
				# no match, check to see if we can repair it
				# since 1s represent transitions, my reasoning is that it's *most* likely that
				# a mismatch would be due to an extra 0 in the stream.
				# we shall see whether I am right or not.
				# to see whether a repair was successful, we see whether future bits are in sync again
				future_offset = offset + 20
				needle_future = needle[future_offset: future_offset + check_window]
				needle_present = needle[offset: offset + check_window]
				haystack_future = haystack[future_offset: future_offset + check_window]
				haystack_present = haystack[offset: offset + check_window]

				future_offset2 = future_offset + 1
				needle_future2 = needle[future_offset2: future_offset2 + check_window]
				haystack_future2 = haystack[future_offset2: future_offset2 + check_window]

				# first, if the futures are in sync already, then we have one bit that was mis-read.
				# assume that it is a missed transition (vs. a single weak bit)
				# and repair it to 1.
				if needle_future == haystack_future:
					if needle[offset] == 0:
						surgeries['needle_zeros'].append(offset)
						message('needle missed transition at {}'.format(offset), 2)
					else:
						surgeries['haystack_zeros'].append(offset)
						message('haystack missed transition at {}'.format(offset), 2)
					needle[offset] = 1
					haystack[offset] = 1
					# trying an alternative: haystack wins
					# needle[offset] = haystack[offset]
				# check if cutting out a 0 will put the streams in sync.
				# if so, do it and continue
				# elif needle_present == haystack_future and haystack[offset] == 0:
				# elif needle_future == haystack_future2 and haystack[offset] == 0:
				# actually, forget the 0, see if just cutting any bit will put them in sync
				elif needle_future == haystack_future2:
					message('haystack {} removed at {}'.format(haystack[offset], offset), 2)
					del haystack[offset]
					if len(haystack) < len(needle):
						stop_offset -= 1
					surgeries['haystack_drops'].append(offset)
					# message('haystack 0 removed at {}'.format(offset), 2)
				# elif haystack_present == needle_future and needle[offset] == 0:
				# elif haystack_future == needle_future2 and needle[offset] == 0:
				elif haystack_future == needle_future2:
					message('needle {} removed at {}'.format(needle[offset], offset), 2)
					del needle[offset]
					if len(needle) < len(haystack):
						stop_offset -= 1
					surgeries['needle_drops'].append(offset)
					# message('needle 0 removed at {}'.format(offset), 2)
				# see if maybe calling two bits weak bits will bring us back in sync
				# elif needle_future2 == haystack_future2:
				# 	if needle[offset] == 0 and needle[future_offset] == 0:
				# 		surgeries.append([offset, 'needle missed two transitions'])
				# 		message('needle missed two transitions at {}'.format(offset), 2)
				# 	elif needle[offset] == 0 and haystack[future_offset] == 0:
				# 		surgeries.append([offset, 'needle, then haystack, missed a transition'])
				# 		message('needle, then haystack, missed a transition at {}'.format(offset), 2)
				# 	elif haystack[offset] == 0 and needle[future_offset] == 0:
				# 		surgeries.append([offset, 'haystack, then needle, missed a transition'])
				# 		message('haystack, then needle, missed a transition at {}'.format(offset), 2)
				# 	else:
				# 		surgeries.append([offset, 'haystack missed two transitions'])
				# 		message('haystack missed two transitions at {}'.format(offset), 2)
				# 	# assume that 1 is correct (missed transitions)
				# 	# though maybe 10 or 01 might be better?  Or something even more subtle?  Hmm.
				# 	needle[offset] = 1
				# 	needle[future_offset] = 1
				# 	haystack[offset] = 1
				# 	haystack[future_offset] = 1
				else:
					if skip_weak:
						if weak_span_start == -1:
							# this is the first weak bit we've found so far, open the span
							weak_span_start = offset
						# every time we get a weak bit reset the count of good bits we need to close it
						weak_span_closing = 0
					else:
						# now we are at a harder decision point
						# if we are too lenient with our repairs, we could incorrectly elevate the match count
						# and wind up thinking we have the track repeat when we don't (and butcher the track in the process)
						# on the other hand, we might have a bad spot in the media that the needle push wouldn't catch.
						# at this point, we are facing either a spurious 1 or a span of mismatches.
						# when we're trying to determine if we have a span of mismatches, we can't be satisfied with just
						# one match.  There are only two values, accidental matches would be pretty easy.
						# So for the moment, just plain bail if these simple fixes don't work.
						# Maybe we can do something more sophisticated about weak bits once we are sure where the track is.
						if offset > 20000:
							# we made it over halfway before we had to bail
							# display what made it fail so I can try to see what kind of repair might be warranted
							message('Irreparable bit mismatch at {}.'.format(offset),2)
							display_bits('    Needle bits   : ', needle_future, 2)
							display_bits('    Haystack bits : ', haystack_future, 2)
						break
			offset += 1
		if offset == stop_offset:
			# we made it all the way through, this is a total match.
			# but we did stop a few bits short of the end, and needle and haystack may now be slightly different lengths
			# needle needs to go all the way to haystack, but the stuff at the end of haystack can be replaced
			# so tack the bits from the end of needle onto the end of haystack so they match
			haystack[offset:] = needle[offset:]
			progress = len(needle)
			success = True
		else:
			# we got kicked out for mismatching before the end
			progress = offset - 1

	return {'ok': success, 'progress': progress, 'needle': needle, 'haystack': haystack, 'surgeries': surgeries}

def analyze_sync(track):
	'''Find regions of sync bits on a track'''
	global options
	# sync regions will have already been gathered during nibblize.
	# This will go through those and try to use them to guess the track size.
	# sort the runs by size descending so we can start looking at the longest ones.
	sorted_sync_regions = sorted(track['sync_regions'], key=lambda run: run[0], reverse=True)
	# For the moment I'm saving sorted list in the track, but I don't know if it's of any use outside.
	# Maybe for display.  I could take this out and save a couple cycles and some memory if it's useless.
	track['sorted_sync_regions'] = sorted_sync_regions
	# For the moment, display the regions we found so that I can eyeball it and try to determine a good algorithm
	if options['verbose']:
		message('These are the "sync spans" found, in decreasing lengths.  Grouped by length, with end offset, distance, then start.', 2)
		prev_nib_offset = 0
		prev_bit_offset = 0
		prev_run = 999999 # guarantees that the first run printed will generate a label
		columns = 0
		for run in sorted_sync_regions:
			# do not bother printing all the 0 and 1 sync regions
			if run[0] < 2:
				break
			# group runs of the same length together.
			if prev_run > run[0]:
				# this length is different, so new label line.
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
	# Try to analyze what we got at the top.  If there's a particularly long sync run, we should have picked it
	# up at least twice, ending one track apart.  It might have been picked up three times.
	# So first check for that.
	if len(sorted_sync_regions) > 2:
		# so long as there are at least multiple sync regions.
		# we want to check 1 and 2, 1 and 3, and 2 and 3.
		for syncs in [[0,1], [0,2], [1,2]]:
			first = sorted_sync_regions[syncs[0]]
			second = sorted_sync_regions[syncs[1]]
			# are they close enough in terms of how long the sync spans are?
			if abs(first[0] - second[0]) < 3:
				# yes, so do they end about a track apart?
				# get them in the right order and check.
				sync_needle = first[2]
				if second[2] < sync_needle:
					sync_needle = second[2]
					sync_haystack = first[2]
				else:
					sync_haystack = second[2]
				# are they about a track apart?
				if 50500 < (sync_haystack - sync_needle) < 52500:
					# yes, they are about a track apart
					# so mark this as the cut point and return
					track['sync_start'] = sync_needle
					track['sync_repeat'] = sync_haystack
					return track
	else:
		# I get this sync regions message more often than I'd have guessed I would.
		# It would seem to mean that the track was absolutely all zeros
		message('Sync nibble analysis not performed, not enough sync regions found to work with.')
	# If the easy guess (using the top three sync regions) did not work, then we could get into some
	# more complex stuff to try to work this out.
	# This has not seemed very reliable so far, so for the moment, I'll bail out early so I can eyeball it.
	# By hand, I can see in Jawbreaker strings of 10 syncs mostly separated by 2990 but with a 6251 and a
	# 17931 interspersed.  So, the complex analysis should see that too, and take the distance between the
	# spaced-out regions as the track length.
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

def display_bits(label, bit_array, level):
	message(label, level, end='')
	for i in range(0, len(bit_array)):
		message('{:1d}'.format(bit_array[i]), level, end='')
	message('', level)

def write_dsk_file(eddfile, tracks):
	'''Write the data out in the form of a 34-track dsk or po file'''
	global options
	# restore this later when po order options are put back in
	# outfile = options['output_basename'] + ('.po' if options['write_po'] else '.dsk')
	outfile = options['output_basename'] + '.dsk'
	message('Writing dsk image to {}'.format('outfile'), 2)
	with open(outfile, mode="wb") as dskfile:
		for track in tracks:
			if (4 * track['track_number']) % 4 == 0 and track['track_number'] < 35:
				dskfile.write(track['dsk_bytes'])

def write_nib_file(eddfile, tracks):
	'''Write the data out in the form of a 34-track nib file'''
	global options
	outfile = options['output_basename'] + '.nib'
	message('Writing nib image to {}'.format('outfile'), 2)
	with open(outfile, mode="wb") as nibfile:
		for track in tracks:
			if (4 * track['track_number']) % 4 == 0 and track['track_number'] < 35:
				# if 'sync_nibstart' in track:
				# 	sync_nibstart = track['sync_nibstart']
				# 	nibfile.write((track['nibbles'])[sync_nibstart: sync_nibstart + 0x1a00])
				# else:
				# 	nibfile.write((track['nibbles'])[:0x1a00])
				nibfile.write(track['nib_nibbles'])

# def write_nit_file(eddfile, tracks):
# 	'''Write the nibble timing data out in the form of a (quarter tracked) nit file'''
# 	# nit files from I'm fEDD Up include all tracks analyzed, not just whole tracks
# 	# This is not going to be very useful for debugging unless the nib also matches I'm fEDD Up's nib
# 	# and actually it might not if we're starting inside the track.  So, I added this, but it might
# 	# be worth taking out again.  Can't tell if I'll ever use it.  Just curious.
# 	global options
# 	outfile = options['output_basename'] + '.nit'
# 	with open(outfile, mode="wb") as nibfile:
# 		for track in tracks:
# 			if 'sync_nibstart' in track:
# 				sync_nibstart = track['sync_nibstart']
# 				nibfile.write((track['nibbles'])[sync_nibstart: sync_nibstart + 0x1a00])
# 			else:
# 				nibfile.write((track['nibbles'])[:0x1a00])

def write_v2d_file(eddfile, tracks):
	'''Write the data out in the form of a half-tracked v2d/d5ni file'''
	global options
	outfile = options['output_basename'] + '.v2d'
	# This in principle can store variable numbers of nibbles per track.
	# Right now the computation of number of nibbles is not done very well, really.
	# requires a track analysis.  For the moment, I'll just store the first 1a00 nibbles on each track.
	# In Virtual II, it seems only to accept half (not quarter) tracks.
	# I think it is possible to not even have enough nibbles found for even 1a00, in which case, write fewer.
	message('Writing v2d image to {}'.format('outfile'), 2)
	with open(outfile, mode="wb") as v2dfile:
		# precompute the lengths so we can get the filesize
		# nibs_to_write = 13312 # cheat massively - VII rejects this
		# nibs_to_write = 7400 # cheat -- this is about as big as I've seen VII accept
		# nibs_to_write = 7168 # cheat -- 1c00
		# nibs_to_write = 6656 # 1a00 - standard for nib
		filesize = 0
		num_tracks = 0
		for track in tracks:
			quarter_track = int(4 * track['track_number'])
			phase = quarter_track % 4
			if phase == 0 or phase == 2:
				filesize += len(track['track_nibbles'])
				# if len(track['track_nibbles']) < nibs_to_write:
				# 	filesize += len(track['track_nibbles'])
				# else:
				# 	filesize += nibs_to_write
				# and four bytes for the track header
				filesize += 4
				if len(track['track_nibbles']) > 0:
					# is it even possible to have zero nibbles, e.g., on an unformatted track?  All zeros?
					num_tracks += 1
				else:
					message('No track nibbles on track {}'.format(track['track_number']), 2)					
		# write the d5ni/v2d header
		# filesize = len(tracks) * (nibs_to_write + 4) # (1a00 + 4) * tracks
		v2dfile.write(struct.pack('>I', filesize)) # size of whole file
		v2dfile.write(b"D5NI") #signature
		v2dfile.write(struct.pack('>H', num_tracks)) # number of tracks
		for track in tracks:
			quarter_track = int(4 * track['track_number'])
			phase = quarter_track % 4
			if phase == 0 or phase == 2:
				if len(track['track_nibbles']) > 0:
					# assuming there are some nibbles (otherwise, skip the track)
					# write the track header
					v2dfile.write(struct.pack('>H', int(4 * track['track_number']))) # quarter track index
					v2dfile.write(struct.pack('>H', len(track['track_nibbles']))) # bytes in this track
					# if len(track['track_nibbles']) < nibs_to_write:
					# 	# if we don't have enough nibbles around to write, then cut the track back
					# 	v2dfile.write(struct.pack('>H', len(track['track_nibbles']))) # bytes in this track
					# else:
					# 	v2dfile.write(struct.pack('>H', nibs_to_write)) # bytes in this track
					# TODO: Maybe try to use sync_nibstart like .nib writing does.  Not now, though.
					# This should write as many nibbles as we have, if it is fewer than nibs_to_write
					v2dfile.write(track['track_nibbles'])

def write_fdi_file(eddfile, tracks):
	'''Write the data out in the form of an FDI file'''
	global options
	outfile = options['output_basename'] + '.fdi'
	message('Writing fdi image to {}'.format('outfile'), 2)
	with open(outfile, mode="wb") as fdifile:
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
			if options['process_quarters'] or phase == 0 or (options['process_halves'] and phase == 2):
				fdifile.write(b"\xd2") # raw GCR
				if len(track['track_bits']) == 0:
					# treat track as unformatted (so we don't even have the 8 header bits)
					# TODO: add partial chaating back in
					fdifile.write(b'\x00\x00')
					track['fdi_bits'] = 0
				else:
					if options['no_translation']:
						track['fdi_bytes'] = bits_to_bytes(track['bits'])
						track['fdi_bits'] = len(track['bits'])
					else:
						track['fdi_bytes'] = bits_to_bytes(track['track_bits'])
						track['fdi_bits'] = len(track['track_bits'])
					track['fdi_write_length'] = 8 + len(track['fdi_bytes'])
					track['fdi_page_length'] = math.ceil(track['fdi_write_length'] / 256)
					fdifile.write(bytes([track['fdi_page_length']]))
			if phase == 0 and not options['process_quarters']:
				# write zeros for lengths of quarter tracks
				fdifile.write(b'\x00\x00\x00\x00\x00\x00')
		# Write out enough zeros after the track data to get us to a page boundary
		if options['process_quarters']:
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
			if options['process_quarters'] or phase == 0:
				if track['fdi_bits'] > 0:
					fdifile.write(struct.pack('>L', track['fdi_bits']))
					fdifile.write(struct.pack('>L', track['index_offset']))
					if options['from_zero']:
						# if asked, we can at this point pass bits straight from the EDD file
						# I am allowing this on the suspicion that it might preserve a little bit
						# more inter-track sync information for track arcing.
						eddbuffer = eddfile.read(16384)
						fdifile.write(eddbuffer[:len(track['track_bits'])])
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
	outfile = options['output_basename'] + '.mfi'
	message('Writing mfi image to {}'.format('outfile'), 2)
	with open(outfile, mode="wb") as mfifile:
		# Preprocess the tracks because we need this information for the header
		# Don't have the same option of storing 2.5x revolutions of bits in MFI
		# So, we need to use the track section we identified.
		eddfile.seek(0)
		current_track = 0.0
		# This has been disabled for now, but I think it is close to working.
		while False:
			if eddbuffer:
				track_index = current_track * 4
				phase = track_index % 4
				# TODO: allow for quarter tracks when the container supports it
				if phase == 0:
					track = tracks[int(track_index)]
					# haystack_offset = track['haystack_offset']
					# track_length = haystack_offset - track[needle_offset]
					# if track_length > 52000:
					# 	haystack_offset = track[needle_offset] + 52000
					# track_bits = (track['bits'])[track['needle_offset']: track['haystack_offset']]
					start_bit = 0
					# TODO: Allow for positioning of the start bit with something sensible.
					cell_length = math.floor(2000000 / len(track_bits))
					if cell_length % 2 == 1:
						cell_length -= 1
					running_length = 0
					zero_span = cell_length
					level_a = True
					odd_trans = False
					mfi_track = []
					mg_b = 1 << 28
					for bit in track['track_bits']:
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

if __name__ == "__main__":
	sys.exit(main())