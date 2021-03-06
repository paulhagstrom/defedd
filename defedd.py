#!/usr/bin/env python3

# defedd - converter/analyzer for EDD files created by Brutal Deluxe's
# I'm fEDD Up.
# Paul Hagstrom, started August 2014, finished when it's finished.
# With some optimization asssistance from John Aycock, and lots of useful
# testing and EDD files from Mark Pilgrim.

# TODO: Consider d13 images for 13-sector images if something uses them.
# mfi support is broken I think, newer mfi spec should handle quarter-tracks.

import sys
import getopt
import struct
import math
import time
from operator import itemgetter
import zlib # needed for mfi
# TODO: explore bitstring https://pythonhosted.org/bitstring/
# to see if it can speed things up
# from bitstring import BitArray, BitStream

# I am leaving this in kind of a disasterous state at the moment.
# I have folded most everything into split at zeros
# I have tried to test it by allowing analysis of just the first two tracks
# I have also tried to bypass all the bit analysis not in split at zeros
# There are still some problems when a track has no discernible patterns
# Still run into array boundedness errors.
# Still am not analyzing bits to resolve (just keeping first instance of gap)
# Still am not entirely convinced that it will work, but it might.
# But right now I'm burned out and want to leave this.  Not even sure -faq works anymore.

# Sneakers works with half tracks, even to v2d

# Some testing notes for things that might be ueful:
# Snack Attack parm guides just give deprotection info (CLC in nibble check I think).
# Wizardry is supposed to have boot disk write protected. Tracks A-E are crucial for counting.
# Copts and Robbers: 0 addr DDAADA data MAX=25? sync; 1.5-13/15.5 by 1 sync
# Choplifter complex: 0, 1-8, 9, A-B, C-1E.5 by .5, 20 CII+

# tracks is an array of track structures, the track structure is:
# track_number: track number (eg. 12.5)
# index_offset: 0 (bit corresponding to index hole, used in creating FDI file)
# bits: bits read from the disk
# zero_spans: bit ranges that are at risk (000s) and not, [[0/1, start, end], ...]
# repeating_regions: bit ranges that are valid repeats [rev1 start, end, rev2 start, end, rev3 start, end]
# options will be stored globally for retrievability.  Set the defaults.
options = {
	'write_protect': False, 
	'sync_tracks': False,
	'process_quarters': True, 'process_halves': True, 'analyze_sectors': True, 
	'verbose': False, 'werbose': False, 'console': [sys.stdout], 'write_log': False,
	'write_full': False, 'no_translation': False, 'analyze_bits': True, 'analyze_nibbles': True,
	'repair_tracks': True, 
	'use_slice': False, 'from_zero': False, 'spiral': False,
	'output_basename': 'outputfilename',
	'output': {'nib': False, 'dsk': False, 'mfi': False, 'fdi': False, 'po': False, 'v2d': False, 'nit': False, 'nic': False, 'png': False},
	'bitstring': False
	}
# status will be also be stored globally, things having to do with full disk
status = {}

track_maximum = 52500 # maximum number of bits we can expect in a track
track_minimum = 48500 # minimum number of bits we can expect in a track
required_match = 300 # minimum number of bits to call a match good
threezeros = bytearray(b'\x00\x00\x00')
syncnibble = bytearray(b'\x00\x01\x01\x01\x01\x01\x01\x01\x01')

# Main analysis control loop
def analyze_disk():
	'''Main analysis control loop'''
	global options
	# Main analysis loop.  This goes through the whole EDD file track by track and analyzes each track.
	# The resulting analyzed data is all accumulated in memory, then written back out in as many formats as requested.
	
	with open(options['output_basename'], mode="rb") as eddfile:
		if options['write_log']:
			options['console'].append(open(options['logfilename'], mode="w"))

		tracks = load_tracks(eddfile)
		# cut back to just first two tracks for testing
		# tracks = tracks[0:2]

		# message('Searching within tracks for patterns.', 2)
		# tracks = track_patterns(tracks)

		# TODO: make this more elegant and/or more correct, also allow for some combinations like sync
		if options['no_translation']:
			for track in tracks:
				track['track_start'] = 0
				track['track_repeat'] = len(track['bits'])
				track['track_bits'] = track['bits'][track['track_start']: track['track_repeat']]
		else:
			if options['sync_tracks']:
				track_groups = sync_tracks(tracks)
				tracks = group_tracks(tracks, track_groups)
			else:
				# create a trivial track group array
				track_groups = []
				for track in tracks:
					track['track_group'] = len(track_groups)
					track_groups.append({'track_group': [len(track_groups)], 'advance_average': 0})
			# tracks = track_patterns(tracks)
			for track in tracks:
				track = split_at_zeros(track)
				track['track_bits'] = track['bit_stream']
				track['track_start'] = 0
				track['track_repeat'] = len(track['track_bits'])

			# here for testing
			options['analyze_bits'] = False

			if options['analyze_bits'] or options['analyze_nibbles'] or options['analyze_sectors']:
				message('Going through track groups, resolving bits and analyzing nibbles.', 2)
				tracks = analyze_track(tracks, track_groups)

			if options['sync_tracks']:
				message('Going through track groups and trimming tracks for sync.', 2)
				tracks = sync_groups(tracks, track_groups)

		message('Writing output files.', 2)
		for output_type, output_file in options['output'].items():
			if output_file:
				output_file(eddfile, tracks)

		# close the log file if we were writing to it
		if options['write_log']:
			(options['console'])[1].close
	return 1

# Take the open file handle and read the bits from the EDD into tracks array
# Return the initialized tracks array.
# This should be the first thing called inside the open file loop.
def load_tracks(eddfile):
	'''create the base tracks array from the edd file'''
	global options, status
	message('load_tracks: Reading tracks from EDD file, converting into bit stream.', 2)
	time_load_tracks = time.clock()
	current_track = 0.0
	tracks = []
	while True:
		eddbuffer = eddfile.read(16384)
		if not eddbuffer:
			break;
		tracks.append({
			'track_number': current_track,
			'index_offset': 0,
			'bits': bytes_to_bits(eddbuffer)
		})
		current_track += 0.25
		# display_bits call below is useful for seeing all the bits on the track, was
		# used when I was trying to see just how noisy extended zero regions that
		# I wrote myself really are.
		# display_bits('Track {:5.2f}:'.format(tracks[-1]['track_number']), tracks[-1]['bits'], 2)
	status['time_load_tracks'] = time.clock() - time_load_tracks
	message('load_tracks: Load/convert took {:5.2f} seconds'.format(status['time_load_tracks']), 2)
	return tracks

def track_patterns(tracks):
	'''Compute the intratrack matches for each track'''
	global options
	message('Searching within tracks for patterns.', 2)
	for track in tracks:
		time_track = time.clock()
		track = split_at_zeros(track)
		# if we consolidated this track into the group then we will have already found these patterns
		if not 'pattern_lengths' in track:
			track['pattern_lengths'], track['track_length'] = find_patterns(track)
		if len(track['pattern_lengths']) > 0:
			track['match_best'] = track['pattern_lengths'][0][0]
			track['track_regions'] = assemble_track_regions(track['pattern_lengths'])
		else:
			track['match_best'] = 0
			track['track_regions'] = []
		track['time_track'] = time.clock() - time_track

		# status output
		status_length = '{:5d}'.format(track['track_length']) if 'track_length' in track else '  n/a'
		status_match = '{:6d}'.format(track['match_best']) if track['match_best'] > 0 else '   n/a'
		# message('Track {:5.2f}: bits: {}, matched: {}, group: {:2d}, time: {:5.2f}s'.format(\
		# 	track['track_number'], status_length, status_match, track['track_group'], track['time_track']), 1)
		message('Track {:5.2f}: bits: {}, matched: {}, time: {:5.2f}s'.format(\
			track['track_number'], status_length, status_match, track['time_track']), 1)

	return tracks

# In a track, look for streams of bits that appear to contain more zeros
# in a row than the amplifier can reliably handle.  Break up the regions
# between those as being more reliable regions for matching.
# The name of this no longer really reflects its role, since everything was split out.
def split_at_zeros(track):
	'''Locate streams of bits that look to contain more zeros in a row than the amplifier can handle'''
	global options, threezeros, track_maximum, track_minimum
	# split the track up by zero regions
	message('Track: {}'.format(track['track_number']), 2)
	track = find_zeros(track)
	track = find_patterns_between_zeros(track)
	track = build_track_map(track)
	track = compress_gaps(track)
	track = resolve_gaps(track)
	track = build_bit_stream(track)
	# Now we've basically got a solid track.
	# Obsolete: remove.
	# first_good = data_regions[0]
	# bits_to_find = bit_stream[:(first_good[2] - first_good[1])]
	# repeat_index = bit_stream.index(bits_to_find, track_minimum)
	# reliable_track = bit_stream[:repeat_index]
	# message('Reliable track is {} bits long'.format(repeat_index), 2)
	# track['reliable_track'] = bit_stream[:repeat_index]
	# for now, for testing, just force the track to be beautiful
	# track['bits'] = bit_stream[:repeat_index]
	# track['bits'].extend(bit_stream[:repeat_index])
	# track['bits'].extend(bit_stream[:repeat_index])
	# track['zero_map'] = track_map
	return track

# Find regions in the track that seem to be stretches of 0s, these are at great risk of
# being misread, since the amplifier randomly produces spurious 1s if it reads too many 0s in a row.
# Areas between these "zero streams" are the more reliable things to search for.
# Strategy is to find three 000s in a row, basically marks the start of a risk zone
# Risk zone starts with 000, ends when the next 1 is not followed by 000 within 25 bits.
# The 25 is an arbitrary guess.  0001...(no nearby 000s)... does not count as a zero stream.
# returns an arrays of regions in track['zero_spans'], with [0/1, start bit, end bit]
# 0 is a zero span, 1 is a reliable span (with margins removed)
# to be conservative the "reliable" regions are shrunk by a margin on each side,
# so there is a margin between each zero region and adjacent reliable region
# I suppose that could be considered a reliablesque region.  If you like.
def find_zeros(track):
	# threezeros was defined globally to save a tiny number of cycles
	global options, threezeros, track_minimum
	if 'zero_spans' in track:
		# we already did this, skip ahead
		return track
	bits = track['bits']
	zero_spans = []
	zero_stream_start = 0
	margin = 10 # 10 bits around a zero stream we found still count as being in a zero stream
	escape_margin = 25 # 0001 that has no 000 within 25 bits marks end of zero stream
	bit_stop = len(bits) - 3 # last place we could find a 000
	in_zero_stream = False
	index  = 0
	while index < bit_stop:
		# find the next 000
		if not in_zero_stream:
			# if we're out of a zero stream go find the next one
			try:
				next_000 = bits.index(threezeros, index)
				# area between index and the next_000 (modulo margin) is a reliable, non-zero stream
				zero_spans.append([1, index + margin, next_000 - margin])
				# move the index up to the zero stream and start collecting it
				index = next_000
				zero_stream_start = index
				in_zero_stream = True
			except ValueError:
				# no more 000s, we're done checking
				# area between index and len(bits) modulo margin is reliable
				zero_spans.append([1, index + margin, len(bits) - margin])
				break
		else:
			# we are in a zero stream, skip ahead to the next 1
			try:
				index = bits.index(0x01, index)
			except ValueError:
				# There are no more 1s left, so track ends in a zero stream, and we're out
				zero_spans.append([0, zero_stream_start, len(bits)])
				break
			# from the 1 that we found, look to see if another 000 occurs in the near future
			try:
				next_000 = bits.index(threezeros, index, index + escape_margin)
				# there are more 000s coming up, so we are still in a zero stream
				# move the index up to them, probably saves a picosecond.
				index = next_000
			except ValueError:
				# There are no 000s in the short term, so we're done with the zero stream
				zero_spans.append([0, zero_stream_start, index])
				in_zero_stream = False
	# We now have a track map, unless we didn't find any 000s in the whole track.  Could happen.
	# In that case, the whole track is essentially "reliable".
	# NOTE: Diversi-DOS.EDD has this property, no zero streams at all.
	# message('Zero spans: {}'.format(zero_spans), 2)
	# TODO: Following code isn't working right.  We got one very long data span first, this adds a second.
	if len(zero_spans) == 1:
		message('No zero streams found in track.', 2)
		# set the "reliable" data region to be the first track_minimum bits.
		# zero_spans.append([1, 0, track_minimum])
		zero_spans = [[1, 0, track_minimum]]
	track['zero_spans'] = zero_spans
	return track

# Search the track for repeats, avoiding patches of 000s, this can usually get the repeats pretty quickly.
# Even standard DOS disks can have trouble with strict matching otherwise because there are often patches of 000s
# between sectors.
# This maybe could be smarter.  We have zero/reliable regions throughout all 2.5 revolutions.
# But it only looks at the reliable regions in the first revolution and tries to find
# matches, disregarding the zero/reliable divisions that were found in the last 1.5 revolutions.
# returns track['repeating_regions'] as [rev1 start, end, rev2 start, end, rev3 start, end]
def find_patterns_between_zeros(track):
	global track_minimum, track_maximum, required_match
	# TODO: The following call is probably unnecessary unless we could get here
	# without having already found the zeros.  The call will short-circuit if
	# the zeros were already located.
	track = find_zeros(track)
	# Go through the reliable regions that start within revolution 1 and find all repeats
	# The findings will be recorded by extending the elements in the zero_spans array
	# to also contain [..., rev2 start, end, rev3 start, end], where 0, 0 means not found
	bits = track['bits']
	data_regions = []
	stop_bit = None
	for region in track['zero_spans']:
		if (stop_bit and region[1] > stop_bit) or region[1] > track_maximum:
			# we've moved past the first revolution, so we're finished
			break
		bit_length = region[2] - region[1]
		if region[0] == 1 and bit_length > required_match: # not a zero stream and long enough
			bits_to_find = bits[region[1]: region[2]] # the reliable region
			index = region[1] + track_minimum # start searching 1 track ahead
			try:
				occurrence = bits.index(bits_to_find, index)
				if occurrence > region[1] + track_maximum:
					# this was found, but beyond the second revolution
					if occurrence < region[1] + track_minimum + track_minimum:
						# we found third revolution but not second revolution
						region.extend([0, 0, occurrence, occurrence + bit_length])
					else:
						# we found something weird, a copy but too far away for second revolution
						# and too close for third.  So, just record it as not found and move on.
						# Shouldn't happen often, if at all.
						region.extend([0, 0, 0, 0])
				else:
					# we found the bits in the second revolution.
					region.extend([occurrence, occurrence + bit_length])
					# can we find third revolution?
					try:
						occurrence = bits.index(bits_to_find, index + track_minimum)
						# yes, we found the third revolution, record it
						region.extend([occurrence, occurrence + bit_length])
					except ValueError:
						# could not find the bits.
						# second repeat is probably off the end of the stream
						region.extend([0, 0])
			except ValueError:
				# did not find the bits anywhere up ahead in any revolution.
				region.extend([0, 0, 0, 0])
			# if we found at least one repeat, trust this as good data
			if region[3] > 0 or region[5] > 0:
				data_regions.append(region[1:])
			# if this is the first good region, move the stop point back to the repeat
			if not stop_bit:
				stop_bit = region[3]
			rev2_distance = region[3] - region[1] if region[3] > 0 else 0
			rev3_distance = region[5] - region[3] if region[5] > 0 else 0
			message('data: {:6d}-{:6d} ({:5d}) {:6d} ({:5d}), {:6d} ({:5d})'.format(region[1], region[2], bit_length,
				region[3], rev2_distance, region[5], rev3_distance), 2)
		else:
			# a zero stream, print a debugging message for now
			message('ZERO: {:6d}-{:6d} ({:5d})'.format(region[1], region[2], bit_length), 2)	
			pass
	track['repeating_regions'] = data_regions
	return(track)

# once we've split at zeros and found repeating regions, assemble them into a map so we have
# boundary conditions for the parts of the track we need to resolve.  The format of the track map is:
# [1/0, rev 1 start, end, rev 2 start, end, rev 3 start, end]
# First element will be a 1 if we have at least rev 1 and rev 2 consistent.
def build_track_map(track):
	global track_maximum, track_minimum, required_match
	edd_string = '       ]        ]        ]        ]        ]        ]        ]        ]       ]       ]'
	track_map = []
	first_good = None
	bit_cursor = [0, 0, 0] # current point for the three revolutions
	bits = track['bits']
	# now, go through the data regions we marked as good and mark the stuff in between as in need of resolution
	for region in track['repeating_regions']:
		bit_length = region[1] - region[0]
		# for the moment ignore "good regions" that don't have a second revolution match
		# (those are regions where revolution 1 matched revolution 3 but not revolution 2)
		# also need to at least make the minimum good region length
		if region[1] > 0 and bit_length > required_match:
			if bit_cursor[0] > 0:
				# the bit cursor has moved already, so we've had a prior good region.
				# add the gap between prior region and this one in both rev 1 and rev 2
				to_resolve = [bits[bit_cursor[0]: region[0]], bits[bit_cursor[1]: region[2]]]
				# Add revolution 3 bits if we can.  Note that it is possible to have two good
				# regions with rev 3 bits separated by one that does not have them.  In that
				# case for now we don't want to try to resolve the rev 3 bits.
				# In intermediate good region without rev 3 bits, third cursor goes back to 0.
				# So: if we have rev 3 bits and we had rev 3 bits before, add the rev 3 gap in.
				if len(to_resolve[1]) == 0:
					message('Added a zero to_resolve from {} to {}'.format(bit_cursor[1], region[2]), 2)
				if region[4] > 0 and bit_cursor[2] > 0 and bit_cursor[2] < region[4]:
					to_resolve.append(bits[bit_cursor[2]: region[4]])
					if len(to_resolve[2]) == 0:
						message('Added a zero to_resolve check bits from {} to {}'.format(bit_cursor[2], region[4]), 2)
				# Add this as a gap to the bit map, between bit cursor 0 and the start of the good region
				# with the gap bits to resolve in the to_resolve array.
				track_map.append([0, bit_cursor[0], region[0], to_resolve])
				message('Added    gap: {} - {} ({})'.format(bit_cursor[0], region[0], region[0] - bit_cursor[0]), 2)
				# show where the EDD card's bytes ended, in case this helps figure out failure modes
				# I don't actually think this is helping, though, after having looked at it.
				if False: # commenting out the display for the moment.
					message(edd_string[(7 - bit_cursor[0] % 8):], 2)
					message(edd_string[(7 - bit_cursor[1] % 8):], 2)
					message(edd_string[(7 - bit_cursor[2] % 8):], 2)
					for gap_segment in to_resolve:
						display_bits('', gap_segment, 2)
			# then add the trusty bits
			# if this is the first one, remember it, we can use this to know when we are done.
			if not first_good:
				first_good = region
			# recall that for the moment I am only considering a region "good" if it has rev 1 and rev 2
			track_map.append([1, region[0], region[1], [bits[region[0]: region[1]]]])
			message('Added trusty: {} - {} ({})'.format(region[0], region[1], bit_length), 2)
			# and set the cursor to the end of the trusty bits
			# if there are rev 3 bits ("check bits") set the third cursor to their end
			# if there are not, zero the third cursor out so it does not get used for next gap
			check_bits = region[4] + bit_length if region[4] > 0 else 0
			bit_cursor = [region[1], region[2] + bit_length, check_bits]
			message('Bit cursor: {}'.format(bit_cursor))
	# now we have all the bits in track_map except the gap bits leading up to the first good bits
	# and those following the last good bits.  This may or may not be long enough to cover the track.
	# One situation is where we started with a good region that is contained in the last good region
	# (the True good region crosses the track boundary, so we got the tail end at the beginning).
	# In that case, we basically want to lop off the beginning and keep the last good bits.
	# Otherwise, the track ends in a gap that needs resolution.  This is slightly trickier.
	# The leading gap bits are the tail end of the gap bits that cross the rev 1/2 boundary.
	# Since we still need to resolve them, we don't know exactly how they line up.
	# If the first good region has rev 3 bits, then we're ok, we at least have two versions
	# of this gap we can resolve, and we can ignore the leading gap.
	# A subcase of that would be one where the first good region is too long to have rev 3
	# bits, but if we lop the tail off it would have.  I should check for that, since that
	# also gives us two copies to resolve while still allowing us to ignore the leading gap.
	# If the first good region simply does not have rev 3 bits -- meaning I guess that there
	# was a read error in rev 3 -- then we would either have to guess on the second copy of
	# the gap bits, or just commit to the only version of the gap bits we have.
	# I think guessing is probably marginally better, so we would have a leading and a
	# trailing gap, where the leading gap resolves against the bits from the first good
	# rev 2 start back as many bits as the leading gap has (since I have no better guess),
	# and the trailing gap -- from the rev 1 bit cursor to the beginning of the guessed second
	# copy of the leading gap -- resolves against the bits from the rev 2 end of the last
	# good data region forward as many bits as the rev 1 trailing gap had.  In that
	# situation, there would be no length pressure during resolution because the gap
	# bits are guaranteed to be the same length, but maybe there will still be some
	# useful resolution possible.  And of course one hopes it barely matters because
	# this is after all in the middle of an unreliable gap.
	# Now, after all that verbiage, let us implement it.
	message('Bit cursor: {}'.format(bit_cursor), 2)
	message('First good: {}'.format(first_good), 2)
	if bit_cursor[0] > first_good[2]:
		# end of last good region was past the beginning of the rev 2 copy of the first one
		# I believe there is no way they can not match, so go ahead and end on a good
		# region, chop off the last good region to correspond to the rev 2 copy
		# it is possible that the last good region was perfectly aligned, though, in which case
		# we eliminate the entire last map chunk.
		if track_map[-1][1] == first_good[2]:
			message('Track ended exactly short of good repeat, lopping off last good block', 2)
			del track_map[-1]
		else:
			message('Track covered, begins and ends on good data, chopping latter block down.', 2)
			# message('Track map -1 was {}'.format(track_map[-1]), 2)
			track_map[-1][2] = first_good[2] - 1 # end of track
			# cut back the bits as well
			track_map[-1][3] = track_map[-1][3][: track_map[-1][2] - track_map[-1][1]]
			# now track_map starts and ends with a good region, and they should flow together
			# message('Track map -1 winds up being {}'.format(track_map[-1]), 2)
	else:
		# end of last good region still short of the full track, so we end on a gap
		if first_good[4] > 0:
			# we have rev 3 bits for the first good region, so we can find two copies of
			# the gap bits the track ends on
			to_resolve = [bits[bit_cursor[0]: first_good[2]], bits[bit_cursor[1]: first_good[4]]]
			track_length = first_good[2] - first_good[0]
			track_map.append([0, bit_cursor[0], track_length, to_resolve])
			message('Track ends on gap, found reliable second copy.', 2)
		else:
			# we don't have rev 3 bits for the first good region.
			# Check to see if we would have if the first good region had not been
			# so freaking long.
			bits_to_find = bits[first_good[0]: first_good[0] + required_match]
			try:
				occurrence = bits.index(bits_to_find, first_good[2] + track_minimum)
				# yes, we found the beginning of the third revolution, so we can use that
				# to demarcate the end of the second copy of the gap
				to_resolve = [bits[bit_cursor[0]: first_good[2]], bits[bit_cursor[1]: occurrence]]
				track_length = first_good[2] - first_good[0]
				track_map.append([0, bit_cursor[0], track_length, to_resolve])
				message('Track ends on gap, found reliable second copy through some effort.', 2)
			except ValueError:
				# even this limited search couldn't find the end of the gap, we have to guess
				# insert leading gap into map and add trailing gap to map
				track_length = first_good[2] - first_good[0]
				# leading gap
				to_resolve = [bits[:first_good[0]], bits[track_length: first_good[2]]]
				track_map.insert(0, [0, 0, first_good[0], to_resolve])
				# trailing gap
				gap_length = track_length - bit_cursor[0]
				to_resolve = [
					bits[bit_cursor[0]: track_length],
					bits[bit_cursor[1], bit_cursor[1] + gap_length]
					]
				track_map.append([0, bit_cursor[0], track_length, to_resolve])
				message('Track gap guessed, begins and ends on gap.', 2)
	# save our work for posterity
	track['track_map'] = track_map
	return track

# Compress gaps (try to extend good regions around the gaps into the gaps), to
# minimize the bits we actually need to resolve
def compress_gaps(track):
	track_map = track['track_map']
	map_size = len(track_map)
	message('Track map size is {}, heading to forward scan:'.format(len(track_map)), 2)
	for segment in range(map_size - 1):
		# moving forward, look for sequence of good-gap
		if track_map[segment][0] == 1 and track_map[segment + 1][0] == 0:
			message('Checking {} and following'.format(segment), 2)
			# good block followed by a gap, try to push the good block in
			good_block = track_map[segment]
			gap_block = track_map[segment + 1]
			edge_bits = bytearray()
			to_resolve = gap_block[3]
			check_bits = True if len(to_resolve) == 3 else False
			# message('Length of to_resolve is {}'.format(len(to_resolve)), 2)
			# message('to_resolve is actually: {}'.format(to_resolve), 2)
			# do the first bits in all variants match?
			while True:
				test_bit = to_resolve[0][0]
				if to_resolve[1][0] == test_bit:
					# first one does
					# if check_bits:
					# 	message('Length of to_resolve[2] is {}'.format(len(to_resolve[2])), 2)
					if check_bits and to_resolve[2][0] != test_bit:
						# second one does not, so we are done
						break
				else:
					# first one does not, so we are done
					break
				# if we got to here, we can shrink the gap and keep going
				edge_bits.append(test_bit)
				# chop to_resolve down
				del to_resolve[0][0]
				del to_resolve[1][0]
				if check_bits:
					del to_resolve[2][0]
				# we have to stop if we eliminated one of the gap options
				if len(to_resolve[0]) == 0 or len(to_resolve[1]) == 0 or (check_bits and len(to_resolve[2])== 0):
					# we have eliminated the gap in at least one of the bit strings, stop here.
					# eliminating the bits in any of the gaps will eliminate the gap.
					to_resolve = []
					message('One of the gaps pushed up to nothing.', 2)
					break
			# add the bits we found to the end of the good block
			good_block[2] += len(edge_bits)
			good_block[3][0].extend(edge_bits)
			message('good_block[:3]: {}'.format(good_block[:3]), 2)
			# Update the left edge of the gap
			gap_block[1] += len(edge_bits)
			gap_block[3] = to_resolve
			message('gap_block[:3]: {}'.format(gap_block[:3]), 2)
			message('Pushed left edge of gap by {} to {} aka {}'.format(len(edge_bits), good_block[2], gap_block[1]))
	# We've now pushed the right edge of the good blocks as far forward as we
	# can.  This could maybe have reduced the gap to nothing if there was just
	# a single spurious bit somewhere.  Go through and clean up gaps that have
	# no bits as one of their options.
	for segment in range(len(track_map), 0, -1):
		check_segment = track_map[segment - 1]
		if check_segment[0] == 0 and check_segment[3] == []:
			# this gap got reduced away and was flagged as such, pull it out
			del track_map[segment - 1]
	# now, move backwards to try to squeeze the gaps from the other end
	map_size = len(track_map)
	message('Track map size is {}, heading to reverse scan:'.format(len(track_map)), 2)
	for segment in range(map_size - 1):
		tnemges = map_size - 1 - segment
		# moving backward, look for sequence of good-gap from the end
		if track_map[tnemges][0] == 1 and track_map[tnemges - 1][0] == 0:
			# good block preceded by a gap, try to push the good block in
			message('Checking {} and preceding'.format(tnemges), 2)
			good_block = track_map[tnemges]
			gap_block = track_map[tnemges - 1]
			message('good_block[:3]: {}'.format(good_block[:3]), 2)
			message('gap_block[:3]: {}'.format(gap_block[:3]), 2)
			edge_bits = bytearray()
			to_resolve = gap_block[3]
			check_bits = True if len(to_resolve) == 3 else False
			# do the last bits in all variants match?
			while True:
				# message('to_resolve: {}'.format(to_resolve), 2)
				# message('edge_bits: {}'.format(edge_bits), 2)
				test_bit = to_resolve[0][-1]
				if to_resolve[1][-1] == test_bit:
					# first one does
					if check_bits and to_resolve[2][-1] != test_bit:
						# second one does not, so we are done
						break
				else:
					# first one does not, so we are done
					break
				# if we got to here, we can shrink the gap and keep going
				edge_bits.append(test_bit)
				# chop to_resolve down
				del to_resolve[0][-1]
				del to_resolve[1][-1]
				if check_bits:
					del to_resolve[2][-1]
				# we have to stop if we eliminated one of the gap options
				if len(to_resolve[0]) == 0 or len(to_resolve[1]) == 0 or (check_bits and len(to_resolve[2])== 0):
					# we have eliminated the gap in at least one of the bit strings, stop here.
					# eliminating the bits in any of the gaps will eliminate the gap.
					to_resolve = []
					message('One of the gaps pulled back to nothing.', 2)
					break
			# add the bits we found to the beginning of the good block
			good_block[1] -= len(edge_bits)
			# reverse the edge bits
			edge_bits.reverse()
			edge_length = len(edge_bits)
			edge_bits.extend(good_block[3][0])
			good_block[3][0] = edge_bits
			# message('good_block[:3]: {}'.format(good_block[:3]), 2)
			# Update the right edge of the gap
			gap_block[2] -= edge_length
			gap_block[3] = to_resolve
			message('gap_block[:3]: {}'.format(gap_block[:3]), 2)
			message('Pulled right edge of gap by {} to {} aka {}'.format(edge_length, good_block[1], gap_block[2]))
	# We've now pushed the left edge of the good blocks as far backward as we
	# can.  This could maybe have reduced the gap to nothing though it is 
	# fairly unlikely that it wasn't already reduced in the forward pass.
	# Not impossible, though, I think. So, go through and clean up gaps that have
	# no bits as one of their options.
	message('Track map has {} entries'.format(len(track_map)), 2)
	for segment in range(len(track_map), 0, -1):
		check_segment = track_map[segment - 1]
		if check_segment[0] == 0 and check_segment[3] == []:
			# this gap got reduced away and was flagged as such, pull it out
			del track_map[segment - 1]
	# And now track map should be as compressed as it can be.
	# It was updated in place, so just return track.
	return track

# This is an IOU.  Right now gaps are resolved by accepting the first option.
def resolve_gaps(track):
	message('resolve_gaps.', 2)
	for segment in track['track_map']:
		if segment[0] == 0:
			# gap
			segment[3] = [segment[3][0]]
	return(track)

# Go through the track map after compression and resolution and build a bit stream
def build_bit_stream(track):
	message('build_bit_stream.', 2)
	bit_stream = bytearray()
	for segment in track['track_map']:
		message('Segment[:3]: {}'.format(segment[:3]), 2)
		bit_stream.extend(segment[3][0])
	track['bit_stream'] = bit_stream
	return(track)

# Short version that just takes the rough cut and keeps it.
def find_patterns(track, second_track = None):
	# First, get a course match, only valid up to the window size used in find_occurrences.
	occurrences = find_occurrences(track, second_track)
	# Flatten the patterns and collect track length votes
	track_length_votes = {}
	patterns_by_length = []
	for source_end in occurrences:
		for span in occurrences[source_end]:
			# collect the votes for track length
			if span[1] in track_length_votes:
				# weight the votes for this length by the length of the match
				track_length_votes[span[1]] += span[0]
			else:
				# otherwise, start a new vote count for this distance
				track_length_votes[span[1]] = span[0]
			patterns_by_length.append(span)
	# Sort the patterns by longest match
	patterns_by_length.sort(key = itemgetter(0), reverse = True)
	# democracy in action, track length will be the one with the most bits found matched at that length
	if len(track_length_votes) > 0:
		votes = sorted(track_length_votes.items(), key=itemgetter(1), reverse = True)
		track_length, highest_vote_count = votes[0]
	else:
		track_length = 0
		highest_vote_count = 0
	# track_length = 0 if patterns_by_length == [] else patterns_by_length[0][1]
	# if it's more than max, cut it in half.  I bet this almost never happens.  Handling it anyway.
	if track_length > track_maximum:
		message('Most popular track length was too high, cutting in half.', 2)
		track_length = int(track_length / 2)
	message('find_patterns: track length, by popular vote: {}'.format(track_length), 2)
	if track_length > 0:
		message('Longest pattern: {}'.format(patterns_by_length[0]), 2)
	return patterns_by_length, track_length

# Do a relatively quick/course scan for patterns in the bits that repeat
# This is used for finding the track length (searching for patterns within one track)
# and for finding sync between adjacent quarter tracks (searching for patterns that appear in both)
# If a second track is provided, it will search (optimized slightly differently) for intertrack patterns.
# Basic logic here is that we move a search-for window through the bit stream at the window size,
# look for places those bits occur in the target stream, and then if a copy is found adjacent to
# a previously found copy, merge them into a larger pattern.  Idea is that it is supposed to go fast.
# Result is a list of patterns, organized by the point at which the source bits end.
def find_occurrences(track, second_track = None):
	'''Do a course-grained scan for patterns in the track'''
	global track_maximum, track_minimum, options
	# The first order of business is to find any zero streams (highly unreliable)
	# so we can try to avoid them when we're doing the match.  We only care about the source bits.
	track = find_zero_streams(track)
	# now, start searching for patterns just after any zero streams

	# matches that are less than the minimum pattern length are considered to be coincidental
	# no point in making the search window any smaller than half the minimum pattern length
	# making it odd because that helps a little with patterns of many 010101s.
	# window/minimum that is much smaller (129/256) seemed to fail more.
	minimum_pattern_length = 1000
	window_size = 501
	source_bits = track['bits']
	bits = second_track['bits'] if second_track else track['bits']
	end_margin = window_size if second_track else (window_size + track_minimum)
	# stop checking source bits when we will hit the end (or won't have a minimal track left)
	source_bit_stop = len(source_bits) - end_margin
	target_bit_stop = len(bits)
	patterns = {}
	start_bit = 0
	total_total_patterns = 0
	# move the search through the source bits, gathering bits to search for a window at at time
	while start_bit < source_bit_stop:
		window_end = start_bit + window_size
		bits_to_find = source_bits[start_bit: window_end]
		occurrences = []
		# start looking at the minimum allowable track distance away (for matches within a track)
		# or from the beginning of the target bits (for matches between tracks).
		# message('Occurrences: start bit {}'.format(start_bit), 2)
		target_bit_start = 0 if second_track else (start_bit + track_minimum)
		while True:
			try:
				next_occurrence = bits.index(bits_to_find, target_bit_start, target_bit_stop)
				# found one, remember where it starts
				occurrences.append(next_occurrence)
				# move offset one past the first one we found and look for the next one
				target_bit_start = next_occurrence + window_size
				# message('Moved offset to {} and continuing'.format(offset), 2)
			except ValueError:
				# no more found, stop looking
				break
		# occurrences is now a list of absolute indices into target bit stream indicating where
		# the bits_to_find window (from start_bit) occurs.
		# Go through the match ranges we have established already and see if any are extended by
		# the occurrences we just found.  They are stored in patterns, which is an array of where
		# prior occurrences/patterns ended.  So, we're looking for patterns that end where these
		# occurrences begin. 
		# pattern format: key=src end, [src end, targ end, src start, targ start, length, distance]
		# no. format is: key=src end, [match size, match dist, src start, src end, targ start, targ end]
		if start_bit in patterns:
			# message('found {} in patterns: {}'.format(start_bit, patterns[start_bit]), 2)
			# there are some patterns whose first half end where the current one started
			# go through those patterns to see if the second point ended at start of one of the current occurrences
			# go backwards so we can delete as we go
			for i in reversed(range(len(patterns[start_bit]))):
				pattern = patterns[start_bit][i]
				if pattern[5] in occurrences:
					# end points of this pattern were in the occurrences, the pattern can be expanded.
					# remove this from the occurrences (don't start a new pattern with it), it is handled
					# message('occurrences before removing {}: {}'.format(pattern[0], occurrences), 2)
					occurrences.remove(pattern[5])
					# message('occurrences after removing {}: {}'.format(pattern[0], occurrences), 2)
					# remove the pattern from the list of those that end at start_bit, since it will now end later.
					# message('patterns[{}] before removing pattern {}: {}'.format(start_bit, pattern, patterns[start_bit]), 2)
					patterns[start_bit].remove(pattern)
					# message('patterns[{}] after removing pattern {}: {}'.format(start_bit, pattern, patterns[start_bit]), 2)
					# pattern match now ends later and is longer
					pattern[0] += window_size # match size increment
					pattern[5] += window_size # target end increment
					pattern[3] = window_end # new source end, end of window
					# add it to patterns with a later end key
					if window_end in patterns:
						patterns[window_end].append(pattern)
					else:
						patterns.update({window_end: [pattern]})
					# message('patterns[{}] after adding pattern {}: {}'.format(window_end, pattern, patterns[window_end]), 2)
				else:
					# if this pattern can NOT be extended by any of the occurrences we found,
					# and it is too short to keep, get rid of it.
					if pattern[0] < minimum_pattern_length:
						patterns[start_bit].remove(pattern)
				# clean up empty pattern list if we made one by deleting things too short to keep
				if patterns[start_bit] == []:
					del patterns[start_bit]
		# we now should have used whatever occurrences we could to extend the patterns
		# any occurrences we have left start their own new pattern, add them
		if occurrences != [] and not window_end in patterns:
			patterns.update({window_end: []})
		for occurrence in occurrences:
			patterns[window_end].append([window_size, occurrence - start_bit, start_bit, window_end, occurrence, occurrence + window_size])
			# patterns[window_end].append([window_end, occurrence + window_size, start_bit, occurrence, window_size, occurrence - start_bit])
		# message('patterns = {}'.format(patterns), 2)
		total_patterns = len(patterns[window_end]) if window_end in patterns else 0
		total_total_patterns += total_patterns
		# message('   Current patterns at {}: {}'.format(window_end, total_patterns), 2)
		# move on to the next window of original bits
		start_bit = window_end
	# message('find_occurrences: Patterns found: {} (overall internal total {})'.format(len(patterns), total_total_patterns), 2)
	# message('patterns = {}'.format(patterns), 2)
	# trim out the patterns that are too short (some might still have survived if they were added at the very end)
	# Flatten the patterns and sort by match length
	# message('Course-grained patterns (minimum length {}):'.format(minimum_pattern_length), 2)
	for source_end in sorted(patterns):
		for span in sorted(patterns[source_end], key=itemgetter(0)):
			starts = [span[2], span[4]]
			ends = [span[3], span[5]]
			match_distance = span[1]
			match_size = span[0]
			if match_size < minimum_pattern_length:
				patterns[source_end].remove(span)
			else:
				pass
				# message('Size {:5d}, Distance {:5d} [{:5d}-{:5d}, {:5d}-{:5d}]'.format(match_size, match_distance, starts[0], ends[0], starts[1], ends[1]), 2)
		if patterns[source_end] == []:
			del patterns[source_end]
	return patterns

# Takes the tracks array, computes sync matches between adjacent tracks.  Result of sync analysis
# is stored within the track dictionary of the higher of the tracks (modifies passed argument),
# and returns the track groups.
def sync_tracks(tracks):
	'''go through the tracks to sync them together and break them into groups'''
	global options, status
	track_groups = []
	# If we are only looking at whole tracks, they are too far apart to allow for syncing
	if not options['process_halves'] and not options['process_quarters']:
		# create a trivial track group array
		for track in tracks:
			track['track_group'] = len(track_groups)
			track_groups.append({'track_group': [len(track_groups)], 'advance_average': 0})
		return track_groups
	message('Looking for intertrack sync and track groupings.', 2)
	# reset the running averages
	track_sync_average = [0, 0]
	group_sync_average = [0, 0, 0]
	sync_match_average = [0, 0, 0]
	# add track zero to the first track group
	track = tracks[0]
	track['sync_advance'] = False
	track['sync_best'] = 0
	track['track_group'] = 0
	track_group = [0]
	# go through the rest of the tracks and check sync with prior track
	for track_index in range(1, len(tracks)):
		track_start_clock = time.clock()
		track = tracks[track_index]
		track_prior = tracks[track_index - 1]
		track['sync_lengths'], track['sync_advance'] = find_patterns(track_prior, track)
		track['sync_best'] = track['sync_lengths'][0][0] if len(track['sync_lengths']) > 0 else 0
		# track['sync_regions'] = assemble_track_regions(track['sync_lengths'])
		# keep an average of the best sync matches we got within this group after the first one
		# a dramatic dip in sync match signals a new track group.  5x seems to work, it is usually
		# an order of magnitude drop.  Actually, Gruds in Space makes me thing 2.5x is safer.
		if (2.5 * track['sync_best']) < sync_match_average[2]:
			# this sync match was bad enough that it indicates we're comparing two different trakcs
			track['sync_advance'] = False
			# store the track group we have been accumulating, and start a new one
			track_groups.append({'track_group': track_group, 'advance_average': group_sync_average[2]})
			track_group = [track_index]
			track['track_group'] = len(track_groups)
			group_sync_average = [0, 0, 0]
		else:
			# accumulate a disk-wide semi-trustable advance average for last resort
			track_sync_average = [track_sync_average[0] + track['sync_advance'], track_sync_average[1] + 1]
			# and keep track of average advance per group as well
			group_sync_average = [group_sync_average[0] + track['sync_advance'], group_sync_average[1] + 1, 0]
			group_sync_average[2] = int(group_sync_average[0] / group_sync_average[1])
			# keep track of average match (used to break groups apart)
			sync_match_average = [sync_match_average[0] + track['sync_best'], sync_match_average[1] + 1, 0]
			sync_match_average[2] = int(sync_match_average[0] / sync_match_average[1])
			# add this to the group of tracks that sync sufficiently together
			track_group.append(track_index)
			# remember in the track which group this track is in
			track['track_group'] = len(track_groups)
		track['sync_time'] = time.clock() - track_start_clock

		# status output

		status_sync = '{:6d}'.format(track['sync_best']) if 'sync_best' in track else '   n/a'
		status_advance = '{:6d}'.format(track['sync_advance']) if 'sync_advance' in track else '   n/a'
		message('Tracks {:5.2f} - {:5.2f} [group: {:2d}] sync match: {} advance: {}, time: {:5.2f}s'.format(\
			track_prior['track_number'], track['track_number'], track['track_group'], status_sync, status_advance, \
			track['sync_time']), 1)
	# if the final track failed to group with the previous one, we will still have a track group hanging
	if track_group != []:
		track_groups.append({'track_group': track_group, 'advance_average': group_sync_average[2]})
	# compute the disk-wide average valid sync advance for use when we have no other guidance
	status['sync_average'] = int(track_sync_average[0] / track_sync_average[1])
	message('track_groups: Overall track advance average: {}'.format(status['sync_average']), 2)
	return track_groups

# This is called after we have already done the sync check and grouping between tracks
# Here we evaluate whether tracks in the group synced well enough together that we can
# just replace all of the track data with the data from one of them
def group_tracks(tracks, track_groups):
	'''Replace bits for tracks in the same group with bits from the best matched track'''
	# This should probably almost never happen, it requires a match that's longer than a track.
	# For the moment I am disabling it.
	return tracks
	# Go through each group of tracks to find the best sync
	message('Consolidating track groups if sync was sufficient.', 2)
	for track_group in track_groups:
		group = track_group['track_group']
		prior_track = -1
		match_track = -1
		best_best_sync = 0
		for track_index in group:
			if prior_track >= 0:
				sync_lengths = tracks[track_index]['sync_lengths']
				best_sync = sync_lengths[0][0] if len(sync_lengths) > 0 else 0
				if best_sync > track_maximum and best_sync > best_best_sync:
					# we have total agreement for at least a track length
					# so we can set all the bits to these
					# but keep going through the group in case we get an even better one
					match_track = track_index
					best_best_sync = best_sync
			prior_track = track_index
		# if we have succeeded, do the surgery
		if match_track >= 0:
			# signal that this track group has been consolidated, and remember which track we took as the source
			track_group['consolidated'] = match_track
			# the sync is long enough to replicate this track across the group
			# do the match computations first, before replicating
			source_track = tracks[match_track]
			message('Track {} can be used for entire group, searching within for patterns.'.format(source_track['track_number']), 2)
			source_track['pattern_lengths'], source_track['track_length'] = find_patterns(source_track)
			for track_index in group:
				# just copy the match track over the other ones (including match results, etc.)
				if track_index != match_track:
					# copy everything else but maintain the original track number
					track_number = tracks[track_index]['track_number']
					tracks[track_index] = tracks[match_track].copy()
					tracks[track_index]['track_number'] = track_number
					# don't advance the tracks in this group now that they match, they are in sync with 0 advance.
					tracks[track_index]['sync_advance'] = 0
					# NOTE: this will result in extremely high "reliability" when reading far away from write center
					# I doubt this is ever really a problem, but if ever some copy protection scheme *expects* noise
					# away from the write center, it is not going to find it.

	return tracks

# This is all basically just wild estimation.
# Track to track read is really not all that consistent.
def sync_groups(tracks, track_groups):
	'''Go through the track groups and try to sync them to one another'''
	global options
	# Loop through the track groups
	prior_track_group = {}
	last_track_length = 51000
	for track_group in track_groups:
		group = track_group['track_group']
		prior_track = -1
		current_offset = 0
		for track_index in group:			
			track = tracks[track_index]
			if prior_track < 0:
				if track_index == 0:
					# track zero, advance zero
					advance = 0
				else:					
					# for the first track in a group, estimate a sync advance.
					# it became first track in a group because we have an unreliable sync advance number.
					# we can either use the advance average of a neighboring group or disk average
					# However, if prior group was consolidated, it advanced a bunch of zeros, so we need
					# to advance the average as many times as there were tracks that did not advance.
					advance = track_group['advance_average'] * len(prior_track_group['track_group'])
			else:
				# this is not the first track in the group.
				advance = tracks[track_index]['sync_advance']
			# at this point, advance tells us how much this track should advance relative to its original read
			# however the track data may be advanced already in a couple of ways.
			# we may have chopped off some of the beginning during bit analysis (in 'already_cut')
			# and we may be starting the track at a non-zero offset (if we did not need to do bit analysis)
			already_advanced = track['already_cut'] if 'already_cut' in track else 0
			already_advanced += track['track_start']
			# advancing is a cumulative thing, track 3's advance is an advance relative to how track 2 already
			# advanced.  What we have computed above is just the relative advance to the prior track.
			# What we now need to determine is how far into the actual bits we need to chop.
			current_offset += advance - already_advanced
			# keep current offset within the first track read
			# TODO: Think about this use of prior track length if track length is zero.
			track_length = tracks[track_index]['track_length']
			track_length = last_track_length if track_length == 0 else track_length
			current_offset %= track_length
			current_offset += (track_length if current_offset < 0 else 0)
			# and now chop the bits
			# I am only chopping off the beginning because we might still be trying to write out an oversample
			message('Track {} advance is {} (already advanced: {})'.format(track['track_number'], advance, already_advanced), 2)
			message('Chopping track {} from {}'.format(track['track_number'], current_offset), 2)
			track['bits'] = track['bits'][current_offset:]
			# this will invalidate pattern matches, but this is basically the last thing we do, so who cares.
			# track['pattern_lengths'], track['track_length'] = adjust_patterns(track['pattern_lengths'], current_offset)
			# track['match_best'] = track['pattern_lengths'][0][0] if len(track['pattern_lengths']) > 0 else 0
			# track['track_regions'] = assemble_track_regions(track['pattern_lengths'])
			prior_track = track_index
			last_track_length = track_length if track_length > 0 else last_track_length
		prior_track_group = track_group
	return tracks

def analyze_track(tracks, track_groups):
	'''do bit analysis and nibble analysis'''
	global options
	for track_group in track_groups:
		# if the tracks in this group were consolidated, only look at the one we used as the source.
		if 'consolidated' in track_group:
			group = [track_group['consolidated']]
		else:
			# there are several tracks in this group, adjacent ones should be reads of these same bits
			group = track_group['track_group']
			# note: a group can wind up spanning more than 4 quarter tracks if a spiral keeps them in sync.
			# so, the "insurance bits" have to come from nearby.  Due to this, reliability needs to be
			# assessed kind of locally, not just on overall degree of sync match.
			# For the moment, I am ignoring the fact that these insurance bits exist, but for tricky ones
			# they could be useful.

		# we should have several reads of the same bits from adjacent tracks, within this track group
		for track_index in group:
			track_start_clock = time.clock()
			track = tracks[track_index]
			# Analyze the bits
			if options['analyze_bits'] and track['match_best'] > 0:
				# note: resolve_bits will modify the bits once it is confident it has the track
				track = resolve_bits(track)
			else:
				# if we are not analyzing the bits, or if the track had no matches, set default start and end
				track['track_start'] = 0
				track['track_repeat'] = track['track_length']
			if options['analyze_nibbles']:
				# note: nibblize can adjust track_start and track_end to align with nibbles
				track = nibblize(track)
				# Analyze track for standard 13/16 formats
				# This can be turned off as an option if we know that the disk has no relevant sectors
				if options['analyze_sectors']:
					track = consolidate_sectors(locate_sectors(track))
			# record the bits now for the purpose of writing out track-sized things.
			track['track_bits'] = track['bits'][track['track_start']: track['track_repeat']]
			# TODO: Test for use_second, write_full, from_zero, spiral here
			track['processing_time'] = time.clock() - track_start_clock
			track_status(track)
		# if the track group was consolidated, copy over the results to the other tracks in the group
		if 'consolidated' in track_group:
			for track_index in track_group['track_group']:
				if track_index != track_group['consolidated']:
					track_number = tracks[track_index]['track_number']
					tracks[track_index] = tracks[track_group['consolidated']].copy()
					tracks[track_index]['track_number'] = track_number
	return tracks

# TODO: Someday make this look nicer and display more relevant information.
def track_status(track):
	'''Display information about track analysis'''
	global options
	trk = "{:5.2f}:".format(track['track_number'])
	bit_length = track['track_repeat'] - track['track_start']
	bit_length = len(track['track_bits']) # this is what fdi write uses to determine empty tracks
	if options['no_translation']:
		bits = " No translation, sending all {:5d} bits to fdi file.".format(len(track['bits']))
	else:
		bits = " {:6d} trackbits".format(bit_length)
		# bits += " {:6d} bits matched".format(track['repair_progress']) #if 'bit_progress' in track else ''
	sectors = " {:2d} sectors".format(len(track['all_sectors'])) if 'all_sectors' in track else ''
	needle = " {:5d} start".format(track['track_start'])
	proc = " {:5.2f}s".format(track['processing_time'])
	# repairs = " {:3d} fixes".format(track['repaired_bits']['surgeries']['total']) if 'repaired_bits' in track else ''
	# reconst = " Recon" if ('bits_reconstituted' in track and track['bits_reconstituted']) else ''
	# message(trk + bits + sectors + needle + proc + repairs + reconst)
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

# This can be SLOW.  This can be very slow.  I've seen it take almost 4 minutes on a track, even if it
# is usually way faster.  I'm not sure what property causes the slowness but I want to eradicate whatever it is.
# Also, I'm not entirely convinced this is important.  
# This is made obsolete for the moment by a shorter version that does not maximize the matches.  Possibly get rid of this.
def find_patternsx(track, second_track = None):
	'''Take course-grained scan and maximize matching patterns in track'''
	# First, get a course match, only valid up to the window size used in find_occurrences.
	occurrences = find_occurrences(track, second_track)
	# Now, patterns has a decent rough cut of where repeats were found, but they are not necessarily
	# as big as they can be.  So, sort the patterns (which will sort them by start bit of the earlier bits),
	# and go through them trying to expand them as far as possible to capture the full extent of the matches
	# (and minimize the gaps between matching bits).
	# Like find_occurrences, this can be used either within a track or between tracks.
	bits = second_track['bits'] if second_track else track['bits']
	source_bits = track['bits'] if second_track else bits
	len_bits = len(bits)
	len_source_bits = len(source_bits)
	expanded_patterns = {}
	patterns_by_length = []
	track_length_votes = {}
	patterns_by_distance = {}
	for source_end in sorted(occurrences):
		# message('  occurrences at {} is {} long, expanded patterns is {} long.'.format(\
		# 	source_end, len(occurrences[source_end]), len(expanded_patterns)), 2)
		# sort by distance so at least we maximize chance of catching repeats
		for span in sorted(occurrences[source_end], key=itemgetter(0)):
		# for span in occurrences[source_end]:
			# message('Now at: source end {}, span {}'.format(source_end, span), 2)
			starts = [span[1], span[2]]
			ends = [source_end, span[0]]
			match_distance = ends[1] - ends[0]
			# check to see if anything at this distance overlaps
			already_done = False
			if match_distance in patterns_by_distance:
				for check_pattern in patterns_by_distance[match_distance]:
					if check_pattern[2] <= starts[0] and check_pattern[3] >= ends[0]:
						# we already have expanded something that covers this
						already_done = True
						break
			if already_done:
				# message('Already expanded something that covers this.', 2)
				continue
			# starts = [span[2], span[3]]
			# ends = [span[0], span[1]]
			# # see if we can avoid pushing this by looking in the patterns we already expanded
			# this was a BAD idea, it slowed things down immensely as expanded_patterns got into the 10000s.
			# already_done = False
			# for check_starts, check_ends in expanded_patterns.items():
			# 	if check_ends[1] - check_ends[0] == match_distance:
			# 		# match distance is the same, so if there is overlap, we already did this one.
			# 		if check_starts[0] <= starts[0] and check_ends[0] >= ends[0] and \
			# 			check_starts[1] <= starts[1] and check_ends[1] >= ends[1]:
			# 			already_done = True
			# 			# message('Already did something covering this one.', 2)
			# if already_done:
			# 	continue
			# starts = patterns[ends]
			# new_ends = [ends[0], ends[1]]
			# bit_distance = starts[1] - starts[0]
			# try to back up the starts
			expand = 0
			pace = 4096
			# while starts[0] > expand and starts[1] > expand:
			while True:
				check_starts = [starts[0] - expand - pace, starts[1] - expand - pace]
				if check_starts[0] < 0 or check_starts[1] < 0:
					# we are going to run off the end here, slow down
					if pace > 1:
						pace = int(pace/2)
						continue
					else:
						# we were already going one bit at a time, we have hit the edge
						break
				# check to see if we can back it up by pace bits
				if source_bits[starts[0] - expand - pace: starts[0] - expand] != bits[starts[1] - expand - pace: starts[1] - expand]:
					# bits stopped matching
					# if we were going fast, slow down 
					if pace > 1:
						pace = int(pace/2)
						continue
					else:
						# we were already going one bit at a time, this is the last mismatch
						# retreat to the last match we had and bail
						expand -= pace
						break
				# we got a match at current pace, so try to move another pace back
				expand += pace
			# if we managed to expand it, update the starts to the new ones
			if expand > 1:
				starts[0] -= expand
				starts[1] -= expand
				# message('Expanded back by {}'.format(expand), 2)
			# At this point, we can see if we just wasted our time.  Is there another pattern
			# we already did that starts here?  If so, move on, we have this one already.
			if (starts[0], starts[1]) in expanded_patterns:
				# message('Already have ({}, {}): {}'.format(starts[0], starts[1], expanded_patterns[(starts[0], starts[1])]), 2)
				continue
			# If we don't already have this, do the same for the end bits, push them ahead as far as we can
			expand = 0
			pace = 20
			while True:
			# while ends[1] + expand < len_bits and ends[0] + expand < len_source_bits:
				# we have not yet run off the end of the stream
				# message('ends: {}, pace {}, expand {}'.format(ends, pace, expand), 2)
				check_ends = [ends[0] + expand + pace, ends[1] + expand + pace]
				if check_ends[0] > len_source_bits or check_ends[1] > len_bits:
					if pace > 1:
						pace = int(pace/2)
						continue
					else:
						break
				if source_bits[ends[0] + expand: ends[0] + pace + expand] != bits[ends[1] + expand: ends[1] + pace + expand]:
					if pace > 1:
						pace = int(pace/2)
						continue
					else:
						expand -= pace
						break
				expand += pace
			if expand > 1:
				ends[0] += expand
				ends[1] += expand
				# message('Expanded forward by {}'.format(expand), 2)
			# we now have the biggest region we can get here.
			# add it to the list of regions we want to keep
			if False:
				message('Adding good region {} to {} with {} to {} ({}, distance: {})'.format(\
					starts[0], ends[0], starts[1], ends[1], ends[0] - starts[0], starts[1] - starts[0]), 2)
				# display_bits('Search bits: ', bits[starts[0]: new_ends[0]], 2)
				# display_bits(' Match bits: ', bits[starts[1]: new_ends[1]], 2)
			# record the pattern so we can block repeats
			if source_bits[starts[0]: ends[0]] != bits[starts[1]: ends[1]]:
				message('ACK!  About to add {} {} to expanded patterns, but bits do not match.', 2)
			expanded_patterns.update({(starts[0], starts[1]): ends})
			# record the pattern with length and track length assertion for returning to caller
			match_length = ends[0] - starts[0]
			match_distance = starts[1] - starts[0]
			# ignore things that wound up being too small
			if match_length > 768:
				patterns_by_length.append([match_length, match_distance, starts[0], ends[0], starts[1], ends[1]])
				# collect the votes for track length
				if match_distance in track_length_votes:
					# weight the votes for this length by the length of the match
					track_length_votes[match_distance] += match_length
				else:
					# otherwise, start a new vote count for this distance
					track_length_votes[match_distance] = match_length
				# add to list of kept patterns by distance
				if not match_distance in patterns_by_distance:
					patterns_by_distance[match_distance] = [patterns_by_length[-1]]
				else:
					patterns_by_distance[match_distance].append(patterns_by_length[-1])

	# tally up the votes to find most popular track length
	if len(track_length_votes) > 0:
		votes = sorted(track_length_votes.items(), key=itemgetter(1), reverse = True)
		track_length, highest_vote_count = votes[0]
	else:
		track_length = 0
		highest_vote_count = 0
	# if the best match was between first and third read, cut it in half
	if track_length > track_maximum:
		track_length = int(track_length / 2)
	# display the results
	if False:
		if second_track:
			display = ' SYNC from {:5.2f}: {:7d} bits ({:7d} votes). '
		else:
			display = 'Track {:5.2f} --- {:7d} bits ({:7d} votes). '
		message(display.format(track['track_number'], track_length, highest_vote_count), 2, end='')
	# sort by longest match
	patterns_by_length.sort(key = itemgetter(0), reverse = True)
	if False:
		if len(patterns_by_length) > 0:
			message('Match: {:7d} ({:7d}/{:7d}) distance {:7d}'.format(patterns_by_length[0][0], \
				patterns_by_length[0][2], patterns_by_length[0][4], patterns_by_length[0][1]), 2)
		else:
			message('No matches :(', 2)
	return patterns_by_length, track_length

# Rather than re-finding patterns if I cut the beginning off of a track, just go through and eliminate
def adjust_patterns(pattern_lengths, cut_point):
	'''Adjust pattern_lengths to accommodate cutting off beginning of track bits without recomputing'''
	global track_maximum
	adjusted_lengths = []
	track_length_votes = {}
	for pattern in pattern_lengths:
		if pattern[3] > cut_point and pattern[5] > cut_point:
			pattern[2] -= cut_point
			pattern[3] -= cut_point
			pattern[4] -= cut_point
			pattern[5] -= cut_point
			if pattern[2] < 0 or pattern[4] < 0:
				# we ran off the beginning, save what we can of this match
				pattern[2] = 0
				pattern[4] = pattern[5] - (pattern[3] - pattern[2])
			match_distance = pattern[4] - pattern[2]
			match_length = pattern[3] - pattern[2]
			pattern[0] = match_length
			pattern[1] = match_distance
			adjusted_lengths.append(pattern)
			if match_distance in track_length_votes:
				track_length_votes[match_distance] += match_length
			else:
				track_length_votes[match_distance] = match_length
	if len(track_length_votes) > 0:
		votes = sorted(track_length_votes.items(), key=itemgetter(1), reverse = True)
		track_length, highest_vote_count = votes[0]
	else:
		track_length = 0
		highest_vote_count = 0
	if track_length > track_maximum:
		track_length = int(track_length / 2)
	adjusted_lengths.sort(key = itemgetter(0), reverse = True)
	return adjusted_lengths, track_length

# break the patterns down by track distance
def split_patterns_by_distance(pattern_lengths):
	patterns_by_distance = {}
	canonical_track_length = pattern_lengths[0][1]
	radius = 0
	# split the patterns by track distance as an offset from the canonical
	for pattern in pattern_lengths:
		delta = abs(pattern[1] - canonical_track_length)
		if delta in patterns_by_distance:
			patterns_by_distance[delta].append(pattern)
		else:
			patterns_by_distance.update({delta: [pattern]})
	# flatten it again
	flat_patterns = []
	for delta in patterns_by_distance:
		for pattern in patterns_by_distance[delta]:
			flat_patterns.append(pattern)
	return flat_patterns

# Build a list of the regions by going down in order of decreasing size and overlaying them until all match regions
# are accounted for.
# This can go badly wrong where there are large regions of identical patterns (like sync bytes) unless we control for
# track length.
def assemble_track_regions(pattern_lengths):
	'''Traverse match regions in decreasing size and reconcile them for track coverage'''
	# Now, build a track by working down through the match lengths and overlaying them
	patterns_by_distance = split_patterns_by_distance(pattern_lengths)
	track_regions = []
	for pattern in patterns_by_distance:
		# message('Checking pattern against regions already collected: {}'.format(pattern), 2)
		# check to see if this pattern conflicts with another one, and if so, skip it
		# since we are working downwards in matching lengths, priority is automatically to the longer match
		cleared_to_add = True
		for check_region in track_regions:
			# message('--comparing region: {}'.format(check_region), 2)
			# unless pattern starts after end of current region or ends before beginning of current region,
			# there is at least some overlap.
			if not (pattern[2] >= check_region[1] or pattern[3] < check_region[0]):
				# if pattern starts after current region and ends before current region, it is entirely contained.
				# I'm not convinced this could ever happen, but I'm checking for it just the same.
				if pattern[2] >= check_region[0] and pattern[3] <= check_region[1]:
					# it is entirely contained within the region we already have, so skip it
					# message('Skipping, {} contained in {}'.format(pattern, check_region), 2)
					# message('--** pattern contained in region, skipping to next pattern.')
					cleared_to_add = False
					break
				# there is some overlap between current region and pattern.
				# The fact that they aren't a single region suggests that there could be a missed/extra bit
				# but there can't have been a lot of them if they overlap.  Allow 2 bits, anything more, discard.
				elif abs(pattern[1] - (check_region[2] - check_region[0])) > 2:
					# track distance for pattern is more than two different from track distance for check_region
					# it does not match a prior region it abuts, so abort
					# (even if it might abut another region more closely).
					# message('--** pattern distance more than 2 from region distance ({})'.format(check_region[2] - check_region[1]), 2)
					cleared_to_add = False
					break
				# if pattern starts before current region, then end of pattern overlaps beginning of region.
				# in this case, current region wins, lop off the end of the pattern.
				elif pattern[2] < check_region[0]:
					# pattern starts before check region, so
					# cut the end of the pattern back to where check region starts
					# message('Pre-trimmed region is {}'.format(pattern), 2)
					adjustment = pattern[3] - check_region[0] # moving end back to region start
					pattern[3] -= adjustment # move source end back
					pattern[5] -= adjustment # move target end back
					pattern[0] = pattern[3] - pattern[2] # recompute length
					# message('--** pattern overlaps region, chopped end to {}.'.format(pattern), 2)
					# message('Trimmed {} for overlap with {}'.format(pattern, check_region), 2)
				# only other option is that pattern ends after current region, so beginning of pattern overlaps end of region.
				# again, region wins, lop off the beginning of the pattern.
				else:
					# pattern ends after check region, so
					# cut the beginning of the pattern forward to where check region ends
					# message('Pre-trimmed region is {}'.format(pattern), 2)
					adjustment = check_region[1] - pattern[2] # move beginning forward to region end
					pattern[2] += adjustment # move source beginning forward
					pattern[4] += adjustment # move target beginning forward
					pattern[0] = pattern[3] - pattern[2] # recompute length
					# message('--** pattern overlaps region, chopped beginning to {}.'.format(pattern), 2)
					# message('Trimmed {} for overlap with {}'.format(pattern, check_region), 2)
				# there used to be a break here, but a single pattern could overlay two bigger ones, we need to check them all
				# break

			# There was no overlap between this region and the pattern, go back and check the rest of the regions.
		# so long as the pattern was not entirely within an existing region, add it.
		# Still unsure if this case could come up.
		if cleared_to_add:
			# message('Adding region {}'.format(pattern), 2)
			track_regions.append([pattern[2], pattern[3], pattern[4], pattern[5]])
	# sort the track regions we wound up with by start
	track_regions.sort(key = itemgetter(0))
	return track_regions	

# An EDD read is about 2.5x around the disk, so for the first half track we actually have three
# reads.  The check bits represent the third read.  We could use them for at least part of the
# track to resolve disputes between bits, but we need to find them.
# The strategy here is based on the idea that we have a list of all match regions already, 
# and so we will process match 1 and 2 and put it into the region map, and then later should
# encounter match 2 and 3 (between the bits that matched 1 and the third read of those bits).
# So, for the region we're looking at (presumed to be the match between 2 and 3), we look back
# in the map to see if we find a match about a track back that matched with 2.  If so, 3 will
# become the check bits for the 1-2 match.
def find_check_bits(track, track_region, track_map):
	'''Locate the check bits for a particular match'''
	# name region members of the current match we are processing
	reg_start, reg_end, match_start, match_end = track_region
	# the format of the check bits is: check bits bounds, prior region that corresponds bounds
	check_bits = [-1, -1, -1, -1]
	found_check_bits = False
	# look back among the matches we already found to see if one ended about a track before this region.
	for check_map in track_map:
		# name map members
		map_type, map_start, map_end, map_match_start, map_match_end = check_map[:5]
		if map_type == 'match':
			# end of first current match minus end of prior found match
			if abs((reg_end - map_end) - track['track_length']) < track['tolerance']:
				# map region ends about a track back from current match end
				# set check bits second match to end where current match ends
				# and first match to end where prior found match ends
				check_bits[1] = reg_end # check bits end with region
				check_bits[3] = map_end # corresponding bits end with map
				found_check_bits = True
				message('Looking back, found a match ending where we want: {}'.format(check_map), 2)
			# start of first current match minus start of prior found match
			if abs((reg_start - map_start) - track['track_length']) < track['tolerance']:
				# check region starts about a track back
				# set check bits second match to start where current match starts
				# and first match to start where prior found match starts
				check_bits[0] = reg_start
				check_bits[2] = map_start
				found_check_bits = True
				message('Looking back, found a match starting where we want: {}'.format(check_map), 2)
			if found_check_bits:
				# we found something, but it may not be the same size (may run off one end or the other)
				# message('Found check match: {}'.format(check_bits), 2)
				if check_bits.count(-1) != 0:
					# we found only one end, not the other
					if check_bits[2] == -1:
						# we found the end but not the beginning
						# this could be either because it is too close to the beginning of the track or
						# because there is a read anomaly that cut the prior match short.
						# set check bits to start where prior found match starts.
						# set matching bits to start as far back from end as prior found match has bits
						check_bits[0] = reg_end - (map_end - map_start)
						check_bits[2] = map_start
						message('Found end but not beginning, so setting beginning to {}/{}'.format(\
							check_bits[0], check_bits[2]), 2)
					else:
						# we found the beginning but not the end
						# so the current match-to-be is too close to the end of the track
						# check bits only for beginning of the match
						# set matching bits to end where they do
						# and set check bits to end as far ahead of the beginning as current match has bits
						check_bits[1] = track_region[1]
						check_bits[3] = map_start + (track_region[1] - track_region[0])
						message('Found beginning but not end, so setting end to {}/{}'.format(\
							check_bits[1], check_bits[3]), 2)
				# check bits found, stop checking
				message('After end adjustment: {}'.format(check_bits), 2)
				break
	# if we found check bits, try to resolve them so that they line up exactly
	# (they may not line up exactly if we had to adjust the length)
	if found_check_bits:
		prior_length = check_bits[3] - check_bits[2]
		current_length = check_bits[1] - check_bits[0]
		# not possible for the matches to be different lengths, so cut back to the shortest
		if prior_length > current_length:
			# check bits were longer
			# set check bits to end after the number of bits in match go by
			check_bits[3] = check_bits[2] + current_length
		elif prior_length < current_length:
			# check bits were shorter
			# set match bits to end after the number of bits in check go by
			check_bits[1] = check_bits[0] + prior_length
		# now do a radial search to find the actual match
		# if we do not find a match, shrink the check bits to see if we can find a smaller match
		max_radius = 3 * track['tolerance']
		max_shrinkage = track['tolerance']
		shrinkage = 0
		bits = track['bits']
		while shrinkage < max_shrinkage:
			# if shrinkage > 0:
			# 	display_bits('Shrunk current: ', bits[check_bits[0] + shrinkage: check_bits[1] - shrinkage], 2)
			# 	display_bits('Full   prior  : ', bits[check_bits[2] + shrinkage - max_radius: check_bits[3] - shrinkage + max_radius], 2)
			radius = 0
			while radius < max_radius:
				synced_check_bits = True
				if bits[check_bits[0] + shrinkage: check_bits[1] - shrinkage] == \
						bits[check_bits[2] + shrinkage + radius: check_bits[3] - shrinkage + radius]:
					# prior was radius closer, shrink the check regions and move prior radius closer
					check_bits[0] += shrinkage
					check_bits[1] -= shrinkage
					check_bits[2] += (radius + shrinkage)
					check_bits[3] += (radius - shrinkage)
					break
				elif bits[check_bits[0] + shrinkage: check_bits[1] - shrinkage] == \
						bits[check_bits[2] + shrinkage - radius: check_bits[3] - shrinkage - radius]:
					# prior was radius further away, shrink the check regions and move prior radius further away
					check_bits[0] += shrinkage
					check_bits[1] -= shrinkage
					check_bits[2] += (shrinkage - radius)
					check_bits[3] -= (shrinkage + radius)
					break
				synced_check_bits = False
				radius += 1
			if synced_check_bits:
				break
			shrinkage += 1
		if not synced_check_bits:
			# I have seen this happen if there are zeros that were luckily read twice (but not thrice) the same way
			# I could try to do submatching but for the moment I will just discard this check match
			check_bits = [-1, -1, -1, -1]
			message('Hey!  Could not sync the check bits!', 2)

	return check_bits

# I accidentally named a second thing build_track_map.  This may be something else.

def build_track_mapx(track):
	'''Go through track regions and assemble a map of matches and gaps for the track'''
	# go through the regions in order, to form a map of the track containing matches and gaps
	# this assumes that track_regions are sorted by start position.  It's possible for two big matches
	# to be separated by one or more little matches at wildly different track distances.
	# We figured a "tolerance" for bit slop based on how many zero spans there seem to be, but this is
	# really a more local thing.  If we have a big match at 51000 and a couple little matches and then a
	# big match at 51050, we really can't permit any matches between them to be anything outside that range.
	# So, then the trick is differenting big from little matches.  So, maybe this should already have been
	# done in the region computation.
	track_length = track['track_length']
	tolerance = track['tolerance']
	zero_streams = track['zero_streams']
	bits = track['bits']
	track_map = []
	index = [0, track_length, -1]
	for track_region in track['track_regions']:
		# name the array values so that the code makes some semblance of sense
		reg_start, reg_end, match_start, match_end = track_region
		next_index = index.copy()
		if abs((match_start - reg_start) - track_length) < tolerance:
			# this track is asserting a length that is witin "tolerance" of the most popular track length.
			# if we are far enough along, check to see if this match corresponds to one about a track back,
			# for those parts that are triply-read
			# This method of finding the check bits is not working very well.
			# The best hope for finding check bits would be to look for matches about a track back
			# So, if we have a match at, e.g., 52000/103000, look back to see if there's a match around 1000.
			# If there is, great, but we don't even care much about matches apart from lining things up.
			# What we really care about is check bits for gaps.  So, find the check bits for two matching
			# regions, and then set the check bits for the gap to be between them.
			# And who knows if the prior match region really ends or begins near where we expect.
			# This is not a good plan.
			# Better would be to actually search for the end bits and the beginning bits (and maybe the middle bits)
			# in the relevant area.
			# And in fact, no reason not to search ahead as well.
			# match_beginning = bits[track_region[0]: track_region[0] + 100]
			# match_end = bits[track_region[1] - 100: track_region[1]]
			# search_start = track_region[2] + track_length - tolerance
			# search_end = track_region[2] + track_length + tolerance + 100
			message('track region: {}'.format(track_region), 2)
			check_bits = find_check_bits(track, track_region, track_map)
			message('check bits: {}'.format(check_bits), 2)

			# add the gap between this match and the previous one to the track map
			if match_start > index[1] and reg_start > index[0]:
				# there is a gap in both reads (a gap in one read will be taken care of between matches)
				# if we found check bits on the prior match (we have an index) and on this one, then record those too
				if index[2] > -1 and check_bits.count(-1) == 0:
					# message('index is {}'.format(index), 2)
					check = 'check {:6d} to {:6d} ({})'.format(index[2], check_bits[2], check_bits[2] - index[2])
				else:
					check = ''
				track_map.append(['gap', index[0], reg_start, index[1], match_start, \
					index[0], reg_start, index[2], check_bits[2]])
				message('.....: {:6d} to {:6d} and {:6d} to {:6d} is a gap (length {:5d} / {:5d}) {}'.format(\
					index[0], track_region[0], index[1], track_region[2], \
					track_region[0] - index[0], track_region[2] - index[1], check), 2)
			# add the match to the track map, and the move the next anticipated thing pointer ahead past the match
			if check_bits.count(-1) == 0:
			# if found_check_bits:
				check = 'check {:6d} to {:6d} ({})'.format(check_bits[2], check_bits[3], check_bits[3] - check_bits[2])
			else:
				check = ''
			track_map.append(['match', reg_start, reg_end, match_start, match_end, \
				check_bits[0], check_bits[1], check_bits[2], check_bits[3]])
			message('MATCH: {:6d} to {:6d} matches {:6d} to {:6d} (length {:5d}, distance {:5d} [{:3d}]) {}'.format(\
				reg_start, reg_end, match_start, match_end, \
				reg_end - reg_start, match_start - reg_start, \
				match_start - reg_start - track_length, check), 2)
			next_index = [reg_end, match_end, check_bits[3]]

		# before we actually advance, check for zero streams in the vicinity, between anticipated next thing
		# and next anticipated next thing.  Right now this is kind of just for information, not sure how it
		# will be useful except in gap resolution.  Don't really want to advance past it as a thing really.
		for (start, end) in [(index[0] - tolerance, next_index[0] + tolerance), (index[1] - tolerance, next_index[1] + tolerance)]:
			for zero_stream in zero_streams:
				# message('zs0: {}, start: {}, end: {}.'.format(zero_stream[0], start, end), 2)
				if zero_stream[0] > start and zero_stream[0] < end:
					# there is a zero stream that starts in the region we will advance over
					message('  000: {:6d} to {:6d} is a zero region (length {}).'.format(\
						zero_stream[0], zero_stream[1], zero_stream[1] - zero_stream[0]), 2)
		# and now advance
		index = next_index.copy()	
	return track_map

def gap_display(columns, index, force=False):
	'''Display a line of the gap display'''
	# Sending None for columns will reset the columns array
	# This will automatically display the line if we have filled it.
	# Sending True for force will display the line even if it is not full
	if columns:
		if force:
			# gap is already finished, force output of whatever we had left over.
			if len(columns[0]) > 0:
				# at least if we even had anything left over
				extra_spaces = ' ' * (16 - len(columns[0]))
				for column in range(0, 8):
					columns[column] += extra_spaces
		# display if we have reached the end of a line
		if len(columns[0]) == 16:
			message('{} {} {} {} {} {} {} {} {:6d}/{:6d} {} '.format(\
				columns[0], columns[1], columns[7], columns[2], columns[3], \
				columns[4], columns[5], columns[6], index[0], index[1], columns[8]), 2)
			columns = None
	if not columns:
		columns = ['', '', '', '', '', '', '', '', '']
	return columns

def gap_display_collect(columns, bits, index, map_segment, pressure, in_zero_stream, sync_character, \
		bit_action_display, resolved_display, skip_target, nibble_display):
	'''Accumulate information on gap processing in columns array for display'''
	if skip_target == 0:
		columns[0] += ' '
	else:
		columns[0] += '{}'.format(bits[index[0]])
	if skip_target == 1:
		columns[1] += ' '
	else:
		columns[1] += '{}'.format(bits[index[1]])
	if map_segment[5:9].count(-1) == 0:
		# there are check bits
		if index[0] >= map_segment[5] and index[0] <= map_segment[6]:						
			columns[7] += '{}'.format(bits[map_segment[7] + (index[0] - map_segment[5])])
		else:
			columns[7] += '.'
	else:
		columns[7] += '.'
	columns[4] += '0' if in_zero_stream else '.'
	# populate the gap pressure display
	if pressure == 0:
		columns[6] += '.'
	elif pressure > 0:
		columns[6] += '+'
	else:
		columns[6] += '-'
	columns[5] += sync_character
	columns[3] += bit_action_display
	columns[2] += resolved_display
	columns[8] += nibble_display
	return columns

def compute_sync_display(short_sync, found_sync, long_sync):
	# Populate the sync display.  Kind of surprisingly complicated.
	if short_sync != 0:
		# short sync found
		if found_sync:
			# long sync also found
			if long_sync == 0:
				# long sync says we are in sync
				if short_sync > 0:
					# short sync says stream 2 had extra bits
					sync_character = '/'
				else:
					# short sync says stream 1 had extra bits
					sync_character = '\\'
			elif long_sync > 0:
				# long sync says stream 2 had extra bits
				if short_sync > 0:
					# both long and short sync say stream 2 had extra bits
					sync_character = ']'
				else:
					# short sync says stream 1 had extra bits, long sync says stream 2 did
					sync_character = '}'
			else:
				# long sync says stream 1 had extra bits
				if short_sync > 0:
					# short sync says stream 2 had extra bits, long sync says stream 1 did
					sync_character = '{'
				else:
					# both long and short sync say stream 1 had extra bits
					sync_character = '['
		else:
			# short sync found, long sync not found
			if short_sync > 0:
				# short sync says stream 2 had extra bits
				sync_character = ')'
			else:
				# short sync says stream 1 had extra bits
				sync_character = '('
	else:
		# short sync not found
		if long_sync == 0:
			# long sync says we are in sync
			sync_character = '|'
		elif long_sync > 0:
			# long sync says stream 2 had extra bits
			sync_character = '>'
		else:
			# long sync says stream 1 had extra bits
			sync_character = '<'
	return sync_character

# This will go through the track, and actually resolve the bit mismatches in the gaps between matches
# it changes the bit stream to the "fixed" one (prior to nibble and/or sector analysis).
# So, we really really hope it does its job right.
def resolve_bits(track):
	'''Resolve/repair the bits'''
	global track_maximum, track_minimum, options, threezeros

	# If the match was long enough to include a whole track, we can short-circuit the analysis
	# TODO: Wait, if it matches like 1.5x a track, does it set the track to be 1.5x too long?  Make sure it doesn't.
	# I'm kind of tempted to remove this, it's not going to speed things up much and it won't yield any different results.
	if track['match_best'] > track_maximum:
		best_match = track['pattern_lengths'][0]
		track['track_length'] = best_match[1]
		track['track_start'] = best_match[2]
		track['already_cut'] = 0
		track['track_repeat'] = track['track_start'] + track['track_length']
		return track

	bits = track['bits']
	pattern_lengths = track['pattern_lengths']
	track_length = track['track_length']

	track = find_zero_streams(track)
	# count how many triple zeros we have and base the tolerance for track length mismatch on that
	# I am just kind of eyeballing it here.
	count_000 = bits.count(threezeros)
	track['tolerance'] = int(count_000 / 75) + 15
	message('We found {} 000s in the bit stream, tolerance is {}.'.format(count_000, track['tolerance']), 2)
	track['track_map'] = build_track_mapx(track)
	# we have a map of the matches and the gaps now to walk through, everything should be contiguous.
	# so now we try to resolve the bits in the gaps between matches
	track_shrink = 0
	last_nibble = None
	next_nibble_start = None
	prior_segment = None
	for map_segment in track['track_map']:
		message('Map segment: {}'.format(map_segment), 2)
		# name the members of map_segment
		map_type, map_start, map_end, map_match_start, map_match_end = map_segment[:5]
		check_match_start, check_match_end, check_start, check_end = map_segment[5:]
		if map_type == 'gap' and map_match_end >= map_match_start:
			# we only really care about the gaps, and gaps that are not negative in the second read
			# (negative in the second read will come up as part of a match for the first gap)
			# quantify the relative pressure to contract for each stream
			# we can deduce the track length assertions of the surrounding matches from the
			# boundaries on our gap
			prior_track_length_off = abs((map_match_start - map_start) - track_length)
			next_track_length_off = abs((map_match_end - map_end) - track_length)
			# if we are going from short to canonical, the pressure is to add bits to stream 1
			# if we are going from long to canonical, the pressure is to remove bits from stream 1
			# if we are going from canonical to long, the pressure is to remove bits from stream 2
			# if we are going from canonical to short, the pressure is to add bits to stream 2
			# and in any event getting closer to canonical is better than not
			# track pressure represents what we want to do to track 1
			# it is negative going short to canonical, or canonical to long, it will be positive
			# idea being this is what it takes to make first match match second match.
			# track_pressure = (next_track_length - track_length) - (prior_track_length - track_length)
			# pressure is more positive the longer tha first read is than the second read
			# (and negative if second is longer)
			pressure = (map_end - map_start) - (map_match_end - map_match_start)
			# before we start, check to see if this gap is zero bits long in either stream
			if map_end - map_start == 0:
				# extra stuff but only in stream 2
				# could only be canonical to long or short to canonical
				# if it is canonical to long, or long to longer, we want to dump the stream 2 bits
				# if it is short to canonical, or shorter to short, we want to keep the stream 2 bits
				# so if prior is closer to canonical than next is, drop
				# if next is closer to canonical than prior is, keep
				extra_bits = bits[map_match_start: map_match_end]
				if prior_track_length_off > next_track_length_off:
					# upcoming match is closer to canonical, so keep the bits 
					# (Prior match will have been shorter than canonical because bits are left in stream 2)
					map_segment.append(extra_bits)
					# deal with the nibbles
					if next_nibble_start:
						next_nibble_start.extend(extra_bits)
					# TODO: this may not really be sufficient, if we just finished a nibble by doing this.
					display_bits('Extra bits between matches added from stream 2: ', extra_bits, 2)
					# this expands the track
					track_shrink -= 1
				else:
					# upcoming match is further from canonical, so drop the bits
					display_bits('Extra bits between matches dropped from stream 2: ', extra_bits, 2)
					map_segment.append(bytearray())
				# skip to next map segment
				continue
			elif map_match_end - map_match_start == 0:
				# extra stuff but only in stream 1
				# dropping stuff in steram 1 seems more dangerous, since it is the guide stream
				# I have certainly seen a case where it causes a misread, though it was a misread
				# that matched stream 2 perfectly.  Don't know.  But for now at least, I will
				# add bits rather than drop them.
				extra_bits = bits[map_start: map_end]
				if prior_track_length_off < next_track_length_off:
					# upcoming match is closer to canonical, so keep the bits
					# (Prior match will have been longer than canonical because bits are left in stream 1)
					# Logic of this seems shaky, but empirically this seems like what I want.
					map_segment.append(extra_bits)
					# TODO: worry about whether there are so many extra bits that we have multiple nibbles
					if next_nibble_start:
						next_nibble_start.extend(extra_bits)
					display_bits('Extra bits between matches added from stream 1: ', extra_bits, 2)
				else:
					# upcoming match is further from canonical, so drop the bits
					display_bits('Extra bits between matches dropped from stream 1: ', extra_bits, 2)
					map_segment.append(bytearray())
					# this shrinks the track
					track_shrink += 1
				# skip to next map segment
				continue
			message('Gap from {} to {} and {} to {}, lengths {} / {}, pressure {}'.format(\
				map_start, map_end, map_match_start, map_match_end, \
				map_end - map_start, map_match_end - map_match_start, pressure), 2, end='')
			if next_nibble_start:
				display_bits(', leading bits for nibbles: ', next_nibble_start, 2, '')
			message('', 2)
			# if there are check bits display them
			# if map_segment[5:9].count(-1) == 0:
			# 	display_bits('Alleged check bits ({}): '.format(map_segment[8] - map_segment[7]), bits[map_segment[7]: map_segment[8]], 2)
			# 	display_bits('           Against ({}): '.format(map_segment[6] - map_segment[5]), bits[map_segment[5]: map_segment[6]], 2)			
			# display_bits('Stream 1: ', bits[map_segment[1]: map_segment[2]], 2)
			# display_bits('Stream 2: ', bits[map_segment[3]: map_segment[4]], 2)
			# now walk through
			gap_resolved = bytearray()
			index = [map_start, map_match_start]
			columns = gap_display(None, index) if options['werbose'] else []
			next_bit_action = -2
			next_bit_source = 0
			next_bit_target = 0
			next_bit_action_display = '?'
			while index[0] < map_segment[2] and index[1] < map_segment[4]:
				line_start = len(gap_resolved)
				in_zero_stream_each = [False, False]
				sync_in_zero_stream_each = [False, False]
				# if either index is in a zero region, then let the zero win
				# TODO: Do this more incrementally, so I don't have to rescan the zero streams for every gap bit
				for stream in [0, 1]:
					for zero_stream in track['zero_streams']:
						if index[stream] >= zero_stream[0] and index[stream] < zero_stream[1]:
							in_zero_stream_each[stream] = True
						if index[stream] + 12 >= zero_stream[0] and index[stream] + 12 < zero_stream[1]:
							sync_in_zero_stream_each[stream] = True
					if in_zero_stream_each[stream] and sync_in_zero_stream_each[stream]:
						break
				in_zero_stream = in_zero_stream_each[0] or in_zero_stream_each[1]
				sync_in_zero_stream = sync_in_zero_stream_each[0] or sync_in_zero_stream_each[1]
				# These flags will determine what we do, the heuristics below will set them
				bit_action = 0 # -1 delete, 0 replace, 1 insert
				bit_source = 0 # bit to insert or replace
				bit_target = 0 # stream in which insertion, deletion, or replacement will happen
				bit_action_display = ' ' # character for action display
				sync_character = ' '

				# only go through the procedure here if we do not have an action order from the previous bit
				if next_bit_action == -2:
					if bits[index[0]] == bits[index[1]]:
						# bits match, add the bit to the resolved gap and proceed
						# this match could be "accidental" of course, but no basis on which to alter the bit.
						# even with the check bits voting, the check bits would get outvoted.
						bit_action = 0 # replace
						bit_source = bits[index[0]] # with whatever is in stream 1 (same as in stream 2)
						bit_action_display = '='
					else:
						# only spring into action if the bits do not match here.
						# now we need to figure out what to do with the mismatch.
						# before we start checking for gap size pressure relief, look for future sync
						# determine whether the next few bits are shifted
						short_sync = 0 # number of bits we would need to add to stream 1 to catch up to stream 2
						radius = 1
						while not in_zero_stream and radius < 4:
							if bits[index[0]: index[0] + 5] == bits[index[1] + radius: index[1] + 5 + radius]:
								# stream 2 had extra bits here
								short_sync = radius
								break
							elif bits[index[1]: index[1] + 5] == bits[index[0] + radius: index[0] + 5 + radius]:
								# stream 1 had extra bits here
								short_sync = -radius
							# this is only looking ahead, rather than looking to see if one stream is already ahead
							# of another one.  Maybe that could happen, but the gamble is that we would have caught
							# it before by looking ahead.
							radius += 1
						# Note that short_sync = 0 means we did not find anything, since we already know that it
						# could not be found at distance 0.
						found_sync = False
						long_sync = 0
						# don't bother looking for future sync if the future check point is in a zero
						# stream, since that will be more damaging than helpful
						if not sync_in_zero_stream and index[0] + 30 < map_segment[2] and index[1] + 30 < map_segment[4]:
							sync_check = bits[index[0] + 12: index[0] + 24]
							radius = 0
							while radius < 6:
								if bits[index[1] + 12 + radius: index[1] + 24 + radius] == sync_check:
									# found sync forward
									found_sync = True
									long_sync = radius
									break
								elif bits[index[1] + 12 - radius: index[1] + 24 - radius] == sync_check:
									# found sync backward
									long_sync = -radius
									found_sync = True
									break
								radius += 1
						sync_character = compute_sync_display(short_sync, found_sync, long_sync)

						if in_zero_stream:
							# if we are currently in a zero stream, not much can be trusted about this bit
							# and we don't care about short sync either.  If we're coming to the end of the
							# zero stream, long sync will be useful in deciding what to do.
							if found_sync:
								# we found a sync point somewhere up ahead, so use that (not gap pressure)
								# to decide what to do.  This case would only arise if sync point is out of
								# the zero stream (since found_sync only gets set if sync point isn't in zero stream)
								if long_sync == 0:
									# we stay in sync with no insertions or deletions, so just take the 0
									bit_action = 0 # replace
									bit_source = 0 # with zero
									bit_action_display = 'Z' # took a zero in zero stream
								elif long_sync > 0:
									# long sync was found, stream 2 was behind stream 1, so stream 2 has extra bits
									# drop the bit from stream 2, hope this will be enough to get us back in sync.
									# (long_sync might be >1, this only moves it back one.)
									bit_action = -1 # delete
									bit_target = 1 # from stream 2
									bit_action_display = 'b' # deleted from stream 2
								else:
									# long sync was found, stream 1 was behind stream 2, so stream 1 has extra bits
									# drop te bit from stream 1, hope
									bit_action = -1 # delete
									bit_target = 0 # from stream 1
									bit_action_display = 'a' # deleted from stream 1
							else:
								# we are in a zero stream, but we don't have any sync point up ahead to guide our
								# choice.  So, use the gap length pressure to decide what to do.
								# We will drop a 1 anytime it is in our pressure interest to do so, otherwise just take a zero.
								if bits[index[0]] == 1 and pressure > 0:
									# pressure to reduce read 1, delete the 1 from stream 1
									bit_action = -1 # delete
									bit_target = 0 # from stream 1
									bit_action_display = 'a' # deleted from stream 1
								elif bits[index[1]] == 1 and pressure < 0:
									# pressure to reduce read 2, delete the 1 from stream 2
									bit_action = -1 # delete
									bit_target = 1 # from stream 2
									bit_action_display = 'b' # deleted from stream 2
								else:
									# we are in a zero stream but the pressure is off, so just swap in a 0 for the 1
									bit_action = 0 # replace
									bit_source = 0 # with zero
									bit_action_display = 'Z' # we went with zero in a zero stream
						else:
							# we are not in a zero stream, the stakes are now higher.  The bits *should* match and do not.
							if short_sync != 0:
								# we found a sync point very close to the mismatch
								# I want to leave it open right now whether I want to condition this on what the prior
								# bit was, but as it stands I do not behave differently depending on that.
								if True or gap_resolved[-1] == 0:
									# we just got a zero previously.
									# Since 0 is based on waiting long enough for no signal, two zeros in a row are
									# speed sensitive.  If the read is going to fast, a zero could be missed, too slow
									# and a zero could be stuck in.  We will be basically goverend by the short sync
									# here.  If adding a zero helps the sync do it, otherwise if deleting a zero
									# helps the sync, do it.
									# if adding another zero before the mismatched 1 helps short sync, add the zero
									if short_sync > 0 and bits[index[0]] == 1:
										# stream 2 has extra bits, stream 1 has a (0)1
										# insert 0 into stream 1 before the 1 and re-read stream 1's bit
										bit_action = 1 # insert
										bit_source = 0 # a zero
										bit_target = 0 # into stream 1
										bit_action_display = '+'
									elif short_sync < 0 and bits[index[1]] == 1:
										# stream 1 has extra bits, stream 2 has a (0)1
										# insert 0 into stream 2 before the 1 and re-read stream 2's bit
										bit_action = 1 # insert
										bit_source = 0 # a zero
										bit_target = 1 # into stream 2
										bit_action_display = '+'
									# adding another zero does not help short sync, so deleting the current zero must.
									elif short_sync > 0:
										# stream 2 has extra bits, and has a second zero.  Delete it.
										bit_action = -1 # delete
										bit_target = 1 # from stream 2
										bit_action_display = 'b'
									else:
										# stream 1 has extra bits, and has a second zero.  Delete it.
										bit_action = -1 # delete
										bit_target = 0 # from stream 1
										bit_action_display = 'a'
							# if we found a longer-term sync
							# NOTE: The way this is set up, an action based on long-term sync trumps one based on short sync
							if found_sync:
								# we found a sync point somewhere up ahead
								if long_sync == 0:
									# forward sync indicates that we do not want to change the length of the streams
									# I have seen a couple of times 11 be read as 00.  Very mysterious.
									# But let's look for it.  Long sync should check out.  Short sync won't if
									# we operate on the first mismatch. 
									if (bits[index[0]: index[0] + 2] == bytearray(b'\x00\x00') and \
												bits[index[1]: index[1] + 2] == bytearray(b'\x01\x01') or \
												bits[index[0]: index[0] + 2] == bytearray(b'\x01\x01') and \
												bits[index[1]: index[1] + 2] == bytearray(b'\x00\x00')):
										bit_action = 0 # replace
										bit_source = 1
										bit_action_display = '^'
										# and then do it again on the next round
										next_bit_action = 0 # replace
										next_bit_source = 1
										bit_action_display = '^'
									else:
										# so, just take whatever stream 1 had
										bit_action = 0 # replace
										bit_source = bits[index[0]] # with stream 1 bit
										bit_action_display = 'A' # took stream 1 bit
								elif long_sync > 0:
									# found sync ahead, meaning stream 2 has extra bits
									# since we are not in a zero stream, adjustment is more dangerous.
									# For the moment, give up and hope we're soon going to be in a zero stream.
									bit_action = 0 # replace
									bit_source = bits[index[0]] # with stream 1 bit
									bit_action_display = 'A' # took stream 1 bit
									# nah.
									# let me try deleting the first bit we see this on.
									bit_action = -1 # delete
									bit_target = 1 # from stream 2
									bit_action_display = 'b'
								else:
									# found sync behind, meaning stream 1 has extra bits
									# since we are not in a zero stream, adjustment is more dangerous.
									# For the moment, give up and hope we're soon going to be in a zero stream.
									bit_action = 0 # replace
									bit_source = bits[index[0]] # with stream 1 bit
									bit_action_display = 'A' # took stream 1 bit
									# nah.
									# let me try deleting the first bit we see this on.
									bit_action = -1 # delete
									bit_target = 0 # from stream 1
									bit_action_display = 'a'
							else:
								# we do not have a sync point to guide us
								# give up and take stream 1 bit
								bit_action = 0 # replace
								bit_source = bits[index[0]] # with stream 1 bit
								bit_action_display = 'A' # took stream 1 bit
				else:
					# we had a previous order, do that.
					bit_action = next_bit_action
					bit_source = next_bit_source
					bit_target = next_bit_target
					bit_action_display = next_bit_action_display
					# and mark it as done
					next_bit_action = -2

				# perform the surgery we elected
				skip_target = -1
				if bit_action == 1:
					# insert
					gap_resolved.append(bit_source) # add bit to resolved bits
					index[bit_target] -= 1 # re-read bit in target stream
					# pressure goes up if inserting in stream 1, down if inserting in stream 2
					pressure += (1 if bit_target == 0 else -1)
					# read 1 expands if we insert in stream 1
					track_shrink -= (1 if bit_target == 0 else 0)
					resolved_display = '{}'.format(bit_source) # display new resolved bit
				elif bit_action == -1:
					# delete
					index[bit_target] += 1 # skip ahead in target stream
					# pressure goes up if deleting from stream 2, down if deleting from stream 1
					pressure += (1 if bit_target == 1 else -1)
					# read 1 shrinks if we delete from stream 1
					track_shrink += (1 if bit_target == 0 else 0)
					skip_target = bit_target # skip in target stream array
					resolved_display = ' ' # skip in resolved display
				else:
					# replace
					gap_resolved.append(bit_source) # add bit to resolved bits
					resolved_display = '{}'.format(bit_source) # display new resolved bit
				# display nibbles of resolved bits
				# since right now this is only for display purposes, only bother if we are displaying it
				if options['werbose']:
					line_bits = gap_resolved[line_start:]
					next_nibble_start, nibble_display = bits_to_nibbles(line_bits, next_nibble_start)

				# display what we did
				if options['werbose']:
					columns = gap_display_collect(columns, bits, index, map_segment, pressure, in_zero_stream, \
						sync_character, bit_action_display, resolved_display, skip_target, nibble_display)
					columns = gap_display(columns, index)
				# proceed to the next bit
				index = [index[0] + 1, index[1] + 1]
			# we have made it through the gap
			# Flush out any undisplayed gap status information
			columns = gap_display(columns, index, True) if options['werbose'] else []
			if next_nibble_start:
				display_bits('Trailing bits after nibbles: ', next_nibble_start, 2)
			if index != [map_segment[2], map_segment[4]]:
				# there are some bits left in the gap
				# for lack of any better ideas, just lop off the bits in the longer one
				# which I can do by doing nothing here.
				stream = 0 if index[0] < map_segment[2] else 1
				dangly_bits = bits[index[stream]: map_segment[2 * stream + 2]]
				display_bits('Some bits hanging off the end of gap in stream {} (ignored): '.format(stream + 1), dangly_bits, 2)
			# display_bits('Resolved gap bits ({}): '.format(len(gap_resolved)), gap_resolved, 2)
			# add the resolved bits to the gap entry in the map
			map_segment.append(gap_resolved)
		elif map_segment[0] == 'match':
			# this is a match
			# display the bits and nibbles if we are in verbose mode
			if options['werbose']:
				# match, display the bits maybe
				message('Matching bits: {}'.format(map_segment[2] - map_segment[1]), 2, end='')
				message(', track length difference: {}'.format((map_segment[3] - map_segment[1]) - track_length), 2, end='')
				if next_nibble_start:
					display_bits(', leading bits for nibbles: ', next_nibble_start, 2, '')
				message('', 2)
				matching_bits = bits[map_segment[1]: map_segment[2]]
				bit_length = len(matching_bits)
				bit_window = 96
				offset = 0
				next_nibble_offset = -len(next_nibble_start) if next_nibble_start else 0
				while offset < bit_length:
					line_bits = matching_bits[offset: offset + bit_window]
					display_bits('{:6d}/{:6d}: '.format(map_segment[1] + offset, map_segment[3] + offset), line_bits, 2, end= ' ')
					if len(line_bits) < bit_window:
						message(' ' * (bit_window - len(line_bits)), 2, end='')
					next_nibble_start, nibble_display = bits_to_nibbles(line_bits, next_nibble_start)
					message(nibble_display, 2)
					offset += bit_window
				if next_nibble_start:
					display_bits('Trailing bits after nibbles: ', next_nibble_start, 2)
				# display_bits('Match ({:5d}): '.format(map_segment[2] - map_segment[1]), bits[map_segment[1]: map_segment[2]], 2)
				# display_bits('   vs ({:5d}): '.format(map_segment[4] - map_segment[3]), bits[map_segment[3]: map_segment[4]], 2)
				# if there are check bits display them
				# if map_segment[5:9].count(-1) == 0:
				# 	display_bits('Alleged check bits ({}): '.format(map_segment[8] - map_segment[7]), bits[map_segment[7]: map_segment[8]], 2)
				# 	display_bits('           Against ({}): '.format(map_segment[6] - map_segment[5]), bits[map_segment[5]: map_segment[6]], 2)			
		prior_segment = map_segment
	# Now we should have everything resolved, build the track bits
	resolved_bits = bytearray()
	longest_match_offset = -1
	longest_match_end_offset = -1
	longest_match = 0
	adjusted_map = []
	# track_shrink = 0
	for map_segment in track['track_map']:
		if map_segment[0] == 'match':
			# remember the longest match we hit so we can use that to try to find the track bounds
			if longest_match < map_segment[2] - map_segment[1]:
				longest_match = map_segment[2] - map_segment[1]
				longest_match_offset = len(resolved_bits)
				longest_match_end_offset = len(resolved_bits) + longest_match
			bits_to_add = bits[map_segment[1]: map_segment[2]]
			segment_start = len(resolved_bits)
			segment_end = len(resolved_bits) + len(bits_to_add)
			# keep track of accumulated track shrink
			# track_shrink += (map_segment[3] - map_segment[1]) - len(bits_to_add)
			adjusted_map.append([segment_start, segment_end, map_segment[1], map_segment[2], map_segment[3]])
			resolved_bits.extend(bits_to_add)
			# display_bits('Match ({:5d}): '.format(len(bits_to_add)), bits_to_add, 2)
		else:
			# gap
			# keep track of accumulated track shrink
			# track_shrink += (map_segment[3] - map_segment[1]) - len(map_segment[9])
			# message('Building resolved bits, adding gap.  Map segment is: {}'.format(map_segment), 2)
			segment_start = len(resolved_bits)
			segment_end = len(resolved_bits) + len(map_segment[9])
			adjusted_map.append([segment_start, segment_end, map_segment[1], map_segment[2], map_segment[3]])
			resolved_bits.extend(map_segment[9])
			# display_bits('  Gap ({:5d}): '.format(len(map_segment[9])), map_segment[9], 2)
	# And now resolved bits should have everything all together
	message('Resolved track bits are now {} bits long.'.format(len(resolved_bits)), 2)
	track['resolved_bits'] = resolved_bits
	track['adjusted_map'] = adjusted_map
	track['longest_resolved_match'] = [longest_match, longest_match_offset, longest_match_end_offset]
	# Find an appropriate place to cut the resolved bits
	start_cut, resolved_length = locate_track_cut(track, track_shrink)

	# remember how much we lopped off the beginning already (for use in sync estimation)
	track['already_cut'] = start_cut
	end_cut = start_cut + resolved_length
	message('Cutting the track from {} to {}'.format(start_cut, end_cut), 2)
	final_bits = resolved_bits[start_cut: end_cut]
	display_bits('  End of track: ', final_bits[-128:], 2)
	display_bits('Start of track: ', final_bits[:128], 2)

	track['bits'] = final_bits[:]
	track['bits'].extend(final_bits)
	track['bits'].extend(final_bits)

	track['track_start'] = 0
	track['track_repeat'] = len(final_bits)
	# track length is used by the nibblizer, so need to make sure it is set
	track['track_length'] = track['track_repeat']
	# track['bit_needle'] = 0
	# track['bit_haystack'] = len(final_bits)

	return track

def bits_to_nibbles(line_bits, next_nibble_start):
	'''Compute nibbles for the verbose displays'''
	nibble_offset = 0
	displayed_some = False
	nibble_display = ''
	while nibble_offset < len(line_bits):
		if next_nibble_start:
			bits_forward = next_nibble_start[:]
			bits_forward.extend(line_bits[nibble_offset:])
			last_nibble = grab_nibble(bits_forward)
			last_nibble['offset'] -= len(next_nibble_start)
		else:
			last_nibble = grab_nibble(line_bits[nibble_offset:])
		next_nibble_offset = nibble_offset + last_nibble['offset'] + 1
		if next_nibble_offset >= len(line_bits) or last_nibble['nibble'] < 128:
			if displayed_some or not next_nibble_start:
				next_nibble_start = line_bits[nibble_offset:]
			else:
				next_nibble_start.extend(line_bits[nibble_offset:])
			break
		nibble_display += '{}{:02x}'.format('_' if last_nibble['leading_zeros'] > 0 else ' ', last_nibble['nibble'])
		displayed_some = True
		next_nibble_start = None
		nibble_offset = next_nibble_offset
	return next_nibble_start, nibble_display

def locate_track_cut(track, track_shrink):
	global threezeros
	# if we get a totally unformatted/garbled track, we could end up with no resolved bits
	# if so, bail out with cut and length zero
	resolved_bits = track['resolved_bits']
	if len(resolved_bits) == 0:
		return 0, 0
	track_map = track['track_map']
	track_length = track['track_length']
	adjusted_map = track['adjusted_map']	
	# due to accommodation to read pressure, the track length may have changed from the original
	# prediction.  Dumbly enough, we have to find it again.
	# Use the first match to do this.
	track_prediction = track_length
	# track_prediction = track_length - track_shrink
	start_cut = 0
	message('Track length before was {} and shrank by {} so new prediction is {}'.format(\
		track_length, track_shrink, track_prediction), 2)
	window_size = 1500
	# spiral out from predicted track length because match pattern might be too common
	radius = 0
	max_radius = track_shrink + (24 * track['tolerance'])
	resolved_length = 0
	found_suitable_bits = False
	best_match = 0 # this actually was unnecessary, it will get set properly.
	# try to pick a track cut that includes the longest match
	longest_match, longest_match_offset, longest_match_end_offset = track['longest_resolved_match']
	max_center = len(resolved_bits) - window_size - max_radius - 12
	message('Max center point is {}, based on window {}, max radius {}, bits {}'.format(\
		max_center, window_size, max_radius, len(resolved_bits)), 2)
	if longest_match_offset + track_prediction < max_center:
		# if we start at the longest match, we should still have room at the end to find end of track
		search_start = longest_match_offset + 12
		search_center = search_start + track_prediction
		found_suitable_bits = True
		message('Starting at beginning of longest match ({} to {}).'.format(longest_match_offset, longest_match_end_offset), 2)
	elif longest_match_end_offset < max_center and longest_match_end_offset - track_prediction - window_size - max_radius > 0:
		# there is room from the beginning to end at the longest match
		search_center = longest_match_end_offset + 12
		search_start = search_center - track_prediction
		found_suitable_bits = True
		message('Ending at end of longest match ({} to {}).'.format(longest_match_offset, longest_match_end_offset), 2)
	else:
		# if we get here, we can neither start with longest match nor end with it
		for map_segment in track_map:
			if map_segment[0] == 'match' and map_segment[2] - map_segment[1] > window_size + 24:
				# match is big enough to do the search
				message('Big enough to do the search: {} to {}'.format(map_segment[1], map_segment[2]), 2)
				if (not found_suitable_bits) or map_segment[2] - map_segment[1] > best_match:
					# this is better than what we have so far
					message('Better than what we had before: {}'.format(best_match), 2)
					if map_segment[1] + 12 + track_prediction < max_center:
						# search center is far enough inland that we can do the radial search
						search_start = map_segment[1] + 12
						search_center = search_start + track_prediction
						message('Search center is {}, max center is {}, good enough.'.format(search_center, max_center), 2)
						found_suitable_bits = True
						best_match = map_segment[2] - map_segment[1]
	if found_suitable_bits:
		message('Searching from first sufficient match at {} around {}'.format(search_start, search_center), 2)
	else:
		# getting desperate now.
		# look for the first window_size bits available that are not in a zero stream
		search_start = 0
		escaped_zeros = False
		while search_start < len(resolved_bits) - track_prediction - window_size - max_radius:
			try:
				next_000 = resolved_bits.index(threezeros, search_start, search_start + window_size + 6)
				# no good, there are zeros, move ahead
				search_start = next_000 + 3
			except ValueError:
				# no zeros here
				escaped_zeros = True
				break
		if escaped_zeros:
			# we found a good start, use that
			# jump ahead 12 bits again to be well clear of zeros
			search_start += 12
			search_center = search_start + track_prediction
			message('Searching for first non-zero-stream bits (at {}) around {}'.format(search_start, search_center), 2)
		else:
			# couldn't find a non-zero start, so give up and use the first bits
			search_start = 0
			search_center = track_prediction
			message('Could not get out of zero stream long enough, just searching for starting bits.', 2)
	search_bits = resolved_bits[search_start: search_start + window_size]
	# run through the adjusted map and work out what to use for predicted track lengths
	start_counting = search_start if search_start < search_center else search_center
	stop_counting = search_center if search_center > search_start else search_start			
	last_track_length = adjusted_map[0][4] - adjusted_map[0][2] # initially reported track length
	adjustment = 0
	for map_segment in adjusted_map:
		if stop_counting < map_segment[0]:
			# this is beyond the point where we care.
			break
		if start_counting < map_segment[1] and stop_counting > map_segment[0]:
			# this segment intervenes (we started counting in it, or passed over it, or stopped counting in it)
			region_shrunk = (map_segment[3] - map_segment[2]) - (map_segment[1] - map_segment[0])
			track_expanded = (map_segment[4] - map_segment[2]) - last_track_length
			adjustment -= region_shrunk
			adjustment += track_expanded
			message('Segment starting at {}/{}: region shrunk {} track expanded {} cumulative adjustment {}'.format(\
				map_segment[0], map_segment[2], region_shrunk, track_expanded, adjustment), 2)
		# else:
		# 	message('Skipping segment {} to {}'.format(map_segment[0], map_segment[1]), 2)
		last_track_length = map_segment[4] - map_segment[2]
	message('Cumulative guess at track length adjustment is {}:'.format(adjustment), 2)
	message('For comparison, track length was {} and track shrink was {}'.format(\
		track_length, track_shrink), 2)
	if search_start < search_center:
		search_center += adjustment
	else:
		search_center -= adjustment
	message('That puts the search center at {}'.format(search_center), 2)
	# display_bits('Looking for: ', search_bits, 2)
	# display_bits('Before search center: ', bits[search_center - max_radius: search_center], 2)
	# display_bits('    at search center: ', bits[search_center: search_center + window_size], 2)
	# display_bits(' after search center: ', bits[search_center + window_size: search_center + max_radius + window_size], 2)
	while radius < max_radius:
		# display_bits(' Find: ', search_bits, 2)
		# display_bits('+{:3d} : '.format(radius), resolved_bits[search_center + radius: search_center + radius + window_size], 2)
		# display_bits('-{:3d} : '.format(radius), resolved_bits[search_center - radius: search_center - radius + window_size], 2)
		if resolved_bits[search_center + radius: search_center + radius + window_size] == search_bits:
			# found forwards
			resolved_length = abs(search_start - (search_center + radius))
			start_cut = search_start if search_start < search_center else search_center + radius
			message('Search bits found forward {} bits, meaning track length of {}'.format(\
				radius, resolved_length), 2)
			break
		elif resolved_bits[search_center - radius: search_center - radius + window_size] == search_bits:
			# found backwards
			resolved_length = abs(search_start - (search_center - radius))
			start_cut = search_start if search_start < search_center else search_center - radius
			message('Search bits found backward {} bits, meaning track length of {}'.format(\
				radius, resolved_length), 2)
			break
		radius += 1
	if resolved_length == 0:
		# we did not succeed in finding the match at all.
		message('WTF.  Cannot find my matching bits.  Searching around {} up to {} and back to {}'.format(\
			search_center, search_center + max_radius + window_size, search_center - max_radius), 2)
		display_bits('Looking for: ', search_bits, 2)
		display_bits('Entire search range: ', resolved_bits[search_center - max_radius: search_center + max_radius + window_size], 2)
		# so just take the predicted length then
		start_cut = 0
		resolved_length = track_prediction
	return start_cut, resolved_length


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
			last_long_nibble = {'offset': offset, 'long_nibbles': long_nibbles_found, 'nibble': nibble}
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
			if long_nibbles_found > 3: # this used to be 6, might be too strict
				# yes, have we found enough short nibbles?
				short_nibbles_found += 1
				if short_nibbles_found > 6: # this used to be 6, might be too strict
					# yep, we've got enough.  So return the last long nibble we found
					return last_long_nibble
		offset += nibble['offset'] + 1
	# if we get to here we failed to find two long nibbles and a short one.
	message('Could not find even enough long nibbles followed by short ones to sync', 2)
	return False

# Nibblize the bit stream.  Also keeps track of timing bits.  Will finish by creating nibble stream
# of entire track (or possibly entire track starting from beginning of best match).
def nibblize(track):
	'''Nibblize the whole track and optimize nibble stream cut point'''
	# if this is an empty track, bail out
	# TODO: Do this in a more elegant way
	if track['track_length'] == 0:
		track['track_nibbles'] = bytearray()
		# track['nibble_best'] = best
		track['all_nibbles'] = bytearray()
		# track['all_timing'] = []
		track['all_offsets'] = []
		# track['nibble_ends'] = []
		# track['sync_regions'] = []
		track['nib_nibbles'] = bytearray()
		return track
	bits = track['bits']
	needle_offset = track['track_start']
	# do this rather than track_repeat because we might have been writing out to an oversampled fdi file
	haystack_start = track['track_start'] + track['track_length']
	# haystack_start = track['track_repeat']
	best = {'ok': False, 'needle': needle_offset, 'haystack': haystack_start, 'nibbles': []}
	# We are done and have a best match of some sort by now (unless we skipped the search, at least).
	# Last thing is to nibblize the whole track (in case we didn't get a total match)
	# This can be slightly better than just nibblizing it from the outset because since we know where our best match
	# is, we can at least align the nibbles by starting at the best match needle
	# So I will discard all nibbles before that.  Evaluation of wisdom of this move pending.
	start_offset = best['needle']
	cut_offset = best['haystack']
	message('Nibblize: initial values: start at {}, cut at {}'.format(start_offset, cut_offset), 2)
	while start_offset < best['needle'] + 12:
		offset = start_offset
		restart = False
		track_nibbles = bytearray()
		track_timing = []
		nibble_offsets = []
		nibble_ends = []
		sync_regions = []
		sync_start = 0
		sync_run = 0
		# message('Starting offset at {:5d}, will record track nibbles just before {:5d}'.format(offset, cut_offset), 2)
		nibble_run_start = ''
		nibble_run_end = ''
		while offset < len(track['bits']):
			nibble = grab_nibble(track['bits'][offset:])
			track_nibbles.append(nibble['nibble'])
			track_timing.append(nibble['leading_zeros'])
			nibble_offsets.append(nibble['offset'])
			nibble_ends.append(offset + nibble['offset'])
			if offset < best['needle'] + 128:
				nibble_run_start += '{:5d}: '.format(offset) if nibble_run_start == '' else ''
				nibble_run_start += ('.' * nibble['leading_zeros'])
				nibble_run_start += '{:2x} '.format(nibble['nibble'])
			if offset > best['haystack'] - 64 and offset < best['haystack'] + 128:
				nibble_run_end += ' ...{:5d}: '.format(offset) if nibble_run_end == '' else ''
				nibble_run_end += ('.' * nibble['leading_zeros'])
				nibble_run_end += '{:2x} '.format(nibble['nibble'])
			# if offset < best['needle'] + 128 or (offset > best['haystack'] - 64 and offset < best['haystack'] + 128):
			# 	message('Nibble: {:2x} with timing {:2d} at offset {:5d}'.format(nibble['nibble'], nibble['leading_zeros'], offset), 2)
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
			if offset >= cut_offset and not 'track_nibbles' in track:
				# if we reached here and found that the cut is not after the right number of bits
				# adjust the start forward and do it again
				if offset > cut_offset:
					start_offset += offset - cut_offset
					cut_offset += offset - cut_offset
					restart = True
					nibble_run_start = ''
					nibble_run_end = ''
					message('Resetting and renibblizing from {} to {} to try to get the track cut precise.'.format(\
						start_offset, cut_offset), 2)
					break
				nibble_run_end += '-//- '
				# message('--- track cut ---', 2)
				track['track_nibbles'] = track_nibbles[:] # freeze it in time, don't equate the pointers
				# message('Track nibbles stored, there are {:5d} of them'.format(len(track['track_nibbles'])), 2)
		if not restart:
			break
	message('Doing full track nibblize and collecting timing bits.', 2)
	message('Starting offset at {:5d}, recording track nibbles just before {:5d}'.format(start_offset, cut_offset), 2)
	message('Nibbles: ' + (' ' * (len(nibble_run_end) - len(nibble_run_start))) + nibble_run_start, 2)
	message('         ' + nibble_run_end, 2)
	# track['nibble_best'] = best
	track['all_nibbles'] = track_nibbles
	# track['all_timing'] = track_timing
	track['all_offsets'] = nibble_offsets
	# track['nibble_ends'] = nibble_ends
	# track['sync_regions'] = sync_regions
	if 'track_nibbles' in track:
		message('Nibbles collected. Track_nibbles is {} long.'.format(len(track['track_nibbles'])), 2)
	else:
		message('Nibbles collected, but.. did not find the track boundary.', 2)
		# fill them all in -- what else can I do?  Not sure where to truncate it otherwise.
		track['track_nibbles'] = track_nibbles
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
				'   ' if sector['addr_checksum_ok'] else 'C{:02x}'.format(sector['addr_checksum']), \
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
				'   ' if sector['data_checksum_ok'] else 'C{:02x}'.format(sector['data_checksum']), \
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


def display_bits(label, bit_array, level, end="\n"):
	message(label, level, end='')
	for i in range(0, len(bit_array)):
		message('{:1d}'.format(bit_array[i]), level, end='')
	message('', level, end)

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

def write_nic_file(eddfile, tracks):
	'''Write the EDD data out in the form of a 35-track nic file'''
	global options
	# restore this later when po order options are put back in
	# outfile = options['output_basename'] + ('.po' if options['write_po'] else '.dsk')
	outfile = options['output_basename'] + '.nic'
	message('Writing nic image to {}'.format('outfile'), 2)
	with open(outfile, mode="wb") as dskfile:
		for track in tracks:
			if (4 * track['track_number']) % 4 == 0 and track['track_number'] < 35:
				track_nickels = bits_to_bytes(track['track_bits'][:65536])
				dskfile.write(track_nickels)

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
	# A v2d/D5NI container can store quarter tracks, but Virtual II only recognizes half tracks.
	message('Writing v2d image to {}'.format('outfile'), 2)
	with open(outfile, mode="wb") as v2dfile:
		# precompute the lengths so we can get the filesize
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
					message('v2d write: No track nibbles on track {}'.format(track['track_number']), 2)					
		# write the d5ni/v2d header
		# filesize = len(tracks) * (nibs_to_write + 4) # (1a00 + 4) * tracks
		v2dfile.write(struct.pack('>I', filesize)) # size of whole file
		v2dfile.write(b"D5NI") #signature
		v2dfile.write(struct.pack('>H', num_tracks)) # number of tracks
		for track in tracks:
			quarter_track = int(4 * track['track_number'])
			phase = quarter_track % 4
			if phase == 0 or phase == 2:
				if 'track_nibbles' in track and len(track['track_nibbles']) > 0:
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

# Write a png file representation of the bits
# Inspired by (and bits of code lightly lifted/adapted from) Charles Mangin's HackFest entry at KansasFest 2015
def write_png_file(eddfile, tracks):
	pass

def write_fdi_file(eddfile, tracks):
	'''Write the data out in the form of an FDI file'''
	global options
	if options['spiral'] and False:
		# it appears (at least with Jawbreaker) that there is a window of about
		# 250 bits in which it will still work, known good was 20007, worked from 19907 up to 20157
		# unfortunately, that disk computes a spiral advance on its own of 11691/10546 = 11118
		# so, the closest working value to what it came up with is 8789 higher.
		# no idea to what extent there is a systematic difference there, will it always be about that low?
		# hence the shotgun to try to figure it out.
		# known-good for Jawbreaker read number 1 (good from 19907 to 20157)
		# options['spiral_advance'] = 20007
		# options['spiral_modulo'] = 51091
		# Jawbreaker read 2 reported 9618/51090, gets to splash at 9618
		# Jawbreaker read 3 reported 9966/51089, gets to splash at 10966, works at 11216.
		start_offset = options['spiral_advance'] - 250
		end_offset = options['spiral_advance'] + 9000
	else:
		start_offset = 0
		end_offset = 0
	offset_increment = 250
	offset = start_offset
	while offset <= end_offset:
		if options['spiral'] and False:
			outfile = options['output_basename'] + '-{}-{}.fdi'.format(offset, options['spiral_modulo'])
		else:
			outfile = options['output_basename'] + '.fdi'.format(offset)
		message('Writing fdi image to {}'.format(outfile), 2)
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
			lengths_written = 0 # keep track of how many track lengths we have written
			for track in tracks:
				phase = (4 * track['track_number']) % 4
				if options['process_quarters'] or phase == 0 or (options['process_halves'] and phase == 2):
					if len(track['track_bits']) == 0:
						# treat track as unformatted (so we don't even have the 8 header bits)
						# TODO: add partial chaating back in
						fdifile.write(b'\x00\x00')
						track['fdi_bits'] = 0
						lengths_written += 1
					else:
						fdifile.write(b"\xd2") # raw GCR
						# start_cut = int(offset * 4 * track['track_number']) % options['spiral_modulo'] if options['spiral'] else 0
						start_cut = 0
						# if options['spiral']:
						# 	message('track {:5.2f}, cut at {:5d}'.format(track['track_number'], start_cut), 2)
						track['fdi_bytes'] = bits_to_bytes(track['track_bits'][start_cut:])
						track['fdi_bits'] = len(track['track_bits'][start_cut:])
						track['fdi_write_length'] = 8 + len(track['fdi_bytes'])
						track['fdi_page_length'] = math.ceil(track['fdi_write_length'] / 256)
						fdifile.write(bytes([track['fdi_page_length']]))
						lengths_written += 1
				if not options['process_quarters']:
					# we are not processing quarters so we will need to stuff lengths at least for half tracks
					if not options['process_halves']:
						# we are processing whole tracks, so stuff zero lengths for quarters 2-4:
						fdifile.write(b'\x00\x00\x00\x00\x00\x00')
						lengths_written += 3
					else:
						# we are processing half tracks, so stuff zero lengths for quarters 2 and 4:
						fdifile.write(b'\x00\x00')
						lengths_written += 1
			# Write out enough zeros after the track data to get us to a page boundary
			for extra_track in range(180 - lengths_written):
				fdifile.write(b"\x00\x00")

			# go to the beginning of the eddfile in case we want to write bytes straight out of it
			eddfile.seek(0)

			for track in tracks:
				track_index = track['track_number'] * 4
				phase = track_index % 4
				if options['process_quarters'] or phase == 0 or (options['process_halves'] and phase == 2):
					if track['fdi_bits'] > 0:
						# message('Writing fdi track {}, fdi bits {}'.format(track['track_number'], track['fdi_bits']), 2)
						fdifile.write(struct.pack('>L', track['fdi_bits']))
						fdifile.write(struct.pack('>L', track['index_offset']))
						if options['from_zero'] and False:
							# if asked, we can at this point pass bits straight from the EDD file
							eddbuffer = eddfile.read(16384)
							fdifile.write(eddbuffer[:len(track['track_bits'])])
						else:
							# bitstream data could actually come straight out of the EDD file
							# but I will use the one that was re-encoded based on repeat location
							fdifile.write(track['fdi_bytes'])
						# pad to a page boundary.
						for x in range(256 - track['fdi_write_length'] % 256):
							fdifile.write(b"\x00")
		offset += offset_increment


def write_mfi_file(eddfile, tracks):
	'''Write the data out in the form of a MESS Floppy Image file'''
	global options
	outfile = options['output_basename'] + '.mfi'
	message('Writing mfi image to {}'.format(outfile), 2)
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

def bits_to_bytes(bits):
	bit_offset = 0
	bytes = bytearray()
	local_bits = bits.copy() # without this, it was altering the bits for the caller
	local_bits.extend([0, 0, 0, 0, 0, 0, 0, 0])
	for bit_offset in range(0, len(local_bits), 8):
		bytes.append(bits_to_byte(local_bits[bit_offset: bit_offset + 8]))
	return bytes

def bits_to_byte(bits):
	byte = 0
	for bit in bits:
		byte = byte << 1
		if bit == 1:
			byte += 1
	return byte

# bytes_to_bits massively sped up by John Aycock, who noticed that
# using a lookup table would be a much faster way to do this.

# initialize the lookup table in global space for later use by bytes_to_bits [JA]
N2bits = []
for i in range(256):
	n = (1 << 8) | i
	binbyte = bin(n)[3:]            # cuts off '0x1' from the beginning
	bitlist = [int(bit) for bit in binbyte]
	assert len(bitlist) == 8
	N2bits.append(bitlist)

# run through the buffer and use the lookup table to blast the bits onto the array [JA]
def bytes_to_bits(eddbuffer):
	'''Convert bytes into component bits'''
	bits = bytearray()
	for byte in eddbuffer:
		bits.extend(N2bits[byte])
	return bits

# Main entry point and options processing
def main(argv=None):
	'''Main entry point'''
	global options, status

	print("defedd - analyze and convert EDD files.")

	try:
		opts, args = getopt.getopt(sys.argv[1:], "hndfmp5txl1qcak0sryvw2u", \
			["help", "nib", "dsk", "fdi", "mfi", "po", "v2d", "nit", "protect", "log",
				"int", "quick", "cheat", "all", "keep", "zero", "slice", "spiral", "sync",
				"verbose", "werbose", "half", "nic"])
	except getopt.GetoptError as err:
		print(str(err))
		usage()
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
		elif o == "-u" or o == "--nic":
			options['output']['nic'] = write_nic_file
			print("Will save UNISDISK NIC file.")
		elif o == "-n" or o == "--nib":
			options['output']['nib'] = write_nib_file
			print("Will save nib file.")
		elif o == "-g" or o == "--png":
			options['output']['png'] = write_png_file
			print("Will save png file.")
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
		elif o == "-2" or o == "--half":
			options['process_quarters'] = False
			options['process_halves'] = True
			print("Will process only half tracks.")
		elif o == "-q" or o == "--quick":
			options['analyze_sectors'] = False
			print("Will skip sector search.")
		elif o == "-c" or o == "--cheat":
			options['write_full'] = True
			print("Cheat and write full EDD 2.5x sample if can't find track boundary.")
		elif o == "-k" or o == "--keep":
			options['repair_tracks'] = False
			print("Will not attempt to repair bitstream.")
		elif o == "-y" or o == "--sync":
			options['sync_tracks'] = False
			print("Will attempt to sync the tracks.")
		# elif o == "-2" or o == "--second":
		# 	options['use_second'] = True
		# 	print("Will use second track copy in sample.")
		elif o == "-a" or o == "--all":
			options['no_translation'] = True
			print("Will write full tracks for all tracks.")
		elif o == "-0" or o == "--zero":
			options['from_zero'] = True
			print("Will write track-length bits starting from beginning of EDD sample for all tracks.")
		elif o == "-r" or o == "--spiral":
			options['spiral'] = True
			print("Will try to keep tracks in sync.")
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

	try:
		eddfilename = args[0]
	except:
		print('You need to provide the name of an EDD file to begin.')
		return 1

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
			if output_file[1] and not (output_file[0] == 'fdi' or output_file[0] == 'nic'):
				print('No translation is only valid for fdi, but since you picked a different output format, analysis is still needed.')
				options['analyze_bits'] = True
				options['analyze_nibbles'] = True
				break

	if options['spiral'] and not (options['process_halves'] or options['process_quarters']):
		print('Cannot do track sync without at least processing half tracks, quarter tracks is better.')
		print('Processing half tracks for now.')
		options['process_halves'] = True

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

	analyze_disk()
	return 1

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
 -g, --png     Write .png file representation (only for -faq at the moment)
 -l, --log     Write .log file of conversion output

 -x, --protect Write protect the disk image if supported (fdi)
Analysis options:
 -z, --nibscan Use double nibble scan to find track
 -q, --quick   Skip standard sector analysis, ok for fdi/mfi/nib
 -1, --int     Consider only whole tracks (not quarter tracks)
 -2, --half    Consider only half (and whole) track (not quarter tracks)
 -c, --cheat   Write full 2.5x bit read for unparseable tracks (vs. unformatted)
 -a, --all     Write full 2.5x bit read for all tracks (i.e. cheat everywhere)
 -s, --slice   Write EDD bits to track length for unparseable tracks (cheat lite)
 -0, --zero    Write EDD bits from 0 instead of found track (slice for formatted)
 -r, --spiral  Write EDD bits in 17000-bit spiral to try to keep track sync
 -k, --keep    Do not attempt to repair bitstream
 -y, --sync    Try to sync the tracks
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

if __name__ == "__main__":
	sys.exit(main())