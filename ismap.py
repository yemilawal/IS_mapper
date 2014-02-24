import logging
import sys, re, os
from argparse import (ArgumentParser, FileType)
from Bio.Blast.Applications import NcbiblastnCommandline

def parse_args():
	'Parse the input arguments, use -h for help'

	parser = ArgumentParser(description='IS mapper')

	# need to add verison info later
	#parser.add_argument("--version", action='version', ...)

	parser.add_argument('--reads', nargs = '+', type = str, required=True, help='Paired end reads for analysing (can be gzipped)')
	parser.add_argument('--forward', type = str, required=False, default = '_1', help = 'Identifier for forward reads if not in MiSeq format (default _1)')
	parser.add_argument('--reverse', type=str, required=False, default='_2', help='Identifier for reverse reads if not in MiSeq format (default _2)')
	parser.add_argument('--reference', type = str, required=True, help='Fasta file for reference gene (eg: insertion sequence) that will be mapped to')
	parser.add_argument('--assemblies', nargs='+', type=str, required=False, help='Contig assemblies, one for each read set')
	parser.add_argument('--type', type=str, required=False, default='fasta', help='Indicator for contig assembly type, genbank or fasta (default fasta)')
	parser.add_argument('--extension', type=str, required=False, default='_contigs', help='Identifier for assemblies (default _contigs')
	parser.add_argument('--typingRef', type=str, required=False, help='Reference genome for typing against')
	parser.add_argument('--coverage', type=float, required=False, default=90.0, help='Minimum coverage for hit to be annotated (default 90.0)')
	parser.add_argument('--percentid', type=float, required=False, default=90.0, help='Minimum percent ID for hit to be annotated (default 90.0')
	parser.add_argument('--log', action="store_true", required=False, help='Switch on logging to file (otherwise log to stdout')

	# Do I need this?
	parser.add_argument('--output', type=str, required=True, help='Location to store output files')

	return parser.parse_args()

# Exception to raise if the command we try to run fails for some reason
class CommandError(Exception):
	pass

def run_command(command, **kwargs):
	'Execute a shell command and check the exit status and any O/S exceptions'
	command_str = ' '.join(command)
	logging.info('Running: {}'.format(command_str))
	try:
		exit_status = call(command, **kwargs)
	except OSError as e:
		message = "Command '{}' failed due to O/S error: {}".format(command_str, str(e))
		raise CommandError({"message": message})
	if exit_status != 0:
		message = "Command '{}' failed with non-zero exit status: {}".format(command_str, exit_status)
		raise CommandError({"message": message})


# Change this so it uses BWA
def bwa_index(fasta_files):
	'Build a bwa index from the given input fasta'

	for fasta in fasta_files:
		built_index = fasta + '.bwt'
		if os.path.exists(built_index):
			logging.info('Index for {} is already built...'.format(fasta))
		else:
			logging.info('Building bwa index for {}...'.format(fasta))
			run_command(['bwa index', fasta])



# Check that an acceptable version of a command is installed
# Exits the program if it can't be found.
# - command_list is the command to run to determine the version.
# - version_identifier is the unique string we look for in the stdout of the program.
# - command_name is the name of the command to show in error messages.
# - required_version is the version number to show in error messages.
def check_command_version(command_list, version_identifier, command_name, required_version):
	try:
		command_stdout = check_output(command_list, stderr=STDOUT)
	except OSError as e:
		logging.error("Failed command: {}".format(' '.join(command_list)))
		logging.error(str(e))
		logging.error("Could not determine the version of {}.".format(command_name))
		logging.error("Do you have {} installed in your PATH?".format(command_name))
		exit(-1)
	except CalledProcessError as e:
		# some programs such as samtools return a non-zero exit status
		# when you ask for the version (sigh). We ignore it here.
		command_stdout = e.output

	if version_identifier not in command_stdout:
		logging.error("Incorrect version of {} installed.".format(command_name))
		logging.error("{} version {} is required by SRST2.".format(command_name, required_version))
		exit(-1)

def get_readFile_components(full_file_path):

	(file_path,file_name) = os.path.split(full_file_path)
	m1 = re.match("(.*).gz",file_name)
	ext = ""
	if m1 != None:
		# gzipped
		ext = ".gz"
		file_name = m1.groups()[0]
	(file_name_before_ext,ext2) = os.path.splitext(file_name)
	full_ext = ext2+ext
	return(file_path,file_name_before_ext,full_ext)

def read_file_sets(args):	

	fileSets = {} # key = id, value = list of files for that sample
	num_paired_readsets = 0

	# paired end
	forward_reads = {} # key = sample, value = full path to file
	reverse_reads = {} # key = sample, value = full path to file
	num_paired_readsets = 0
	num_single_readsets = 0
	for fastq in args.reads:
		(file_path,file_name_before_ext,full_ext) = get_readFile_components(fastq)
		# try to match to MiSeq format:
		m=re.match("(.*)(_S.*)(_L.*)(_R.*)(_.*)", file_name_before_ext)
		if m==None:
			# not default Illumina file naming format, expect simple/ENA format
			m=re.match("(.*)("+args.forward+")$",file_name_before_ext)
			if m!=None:
				# store as forward read
				(baseName,read) = m.groups()
				forward_reads[baseName] = fastq
			else:
				m=re.match("(.*)("+args.reverse+")$",file_name_before_ext)
				if m!=None:
				# store as reverse read
					(baseName,read) = m.groups()
					reverse_reads[baseName] = fastq
				else:
					print "Could not determine forward/reverse read status for input file " + fastq
		else:
			# matches default Illumina file naming format, e.g. m.groups() = ('samplename', '_S1', '_L001', '_R1', '_001')
			baseName, read  = m.groups()[0], m.groups()[3]
			if read == "_R1":
				forward_reads[baseName] = fastq
			elif read == "_R2":
				reverse_reads[baseName] = fastq
			else:
				print "Could not determine forward/reverse read status for input file " + fastq
				print "  this file appears to match the MiSeq file naming convention (samplename_S1_L001_[R1]_001), but we were expecting [R1] or [R2] to designate read as forward or reverse?"
				fileSets[file_name_before_ext] = fastq
				num_single_readsets += 1
	# store in pairs
	for sample in forward_reads:
		if sample in reverse_reads:
			fileSets[sample] = [forward_reads[sample],reverse_reads[sample]] # store pair
			num_paired_readsets += 1
		else:
			fileSets[sample] = [forward_reads[sample]] # no reverse found
			num_single_readsets += 1
			logging.info('Warning, could not find pair for read:' + forward_reads[sample])
	for sample in reverse_reads:
		if sample not in fileSets:
			fileSets[sample] = reverse_reads[sample] # no forward found
			num_single_readsets += 1
			logging.info('Warning, could not find pair for read:' + reverse_reads[sample])

	if num_paired_readsets > 0:
		logging.info('Total paired readsets found:' + str(num_paired_readsets))	
	if num_single_readsets > 0:
		logging.info('Total single reads found:' + str(num_single_readsets))

	return fileSets

def get_kmer_size(read):

	cmd = "gunzip -c " + read + " | head -n 400"
	info = os.popen(cmd)

	seqs = []
	count = 1

	for line in info:
		if count % 4 == 2:
			seqs.append(line)
			count = count + 1
		else:
			count = count + 1

	lens = []
	total = 0

	for i in seqs:
		lens.append(len(i.split('\n')[0]))

	for i in lens:
		total = total + i

	total = total / 100

	sKmer = total / 3
	eKmer = total / 3 * 2

	return sKmer, eKmer

def check_blast_database(fasta):

	database_path = fasta + ".nin"

	if os.path.exists(database_path):
		logging.info('Index for {} is already built...'.format(fasta))
	else:
		logging.info('Building blast index for {}...'.format(fasta))
		print ' '.join(['makeblast db -in', fasta, '-dbtype nucl'])
		#run_command(['makeblast db -in', fasta, '-dbtype nucl'])


def main():

	args = parse_args()

	#set up logfile
	if args.log is True:
		logfile = args.output + ".log"
	else:
		logfile = None
	logging.basicConfig(
		filename=logfile,
		level=logging.DEBUG,
		filemode='w',
		format='%(asctime)s %(message)s',
		datefmt='%m/%d/%Y %H:%M:%S')
	logging.info('program started')
	logging.info('command line: {0}'.format(' '.join(sys.argv)))

	fileSets = read_file_sets(args)
	print fileSets

	output_dir = args.output

	for sample in fileSets:
		forward_read = fileSets[sample][0]
		reverse_read = fileSets[sample][1]
		output_sam = sample + '.sam'
		five_bam = sample + '_5.bam'
		three_bam = sample + '_3.bam'

		sKmer, eKmer = get_kmer_size(forward_read)

		VOdir_five = sample + "_VO_5"
		VOdir_three = sample + "_VO_3"
		five_assembly = sample + "_5_contigs.fasta"
		three_assembly = sample + "_3_contigs.fasta"

		#map to IS reference
		print ' '.join(['bwa mem', args.reference, forward_read, reverse_read, '>', output_sam])

		#get five prime end
		print ' '.join(['samtools view -Sb -f 36', output_sam, '>', five_bam])

		#get three prime end
		print ' '.join(['samtools view -Sb -f 4 -F 40', output_sam, '>', three_bam])

		#assemble five prime end with VO
		print ' '.join(['./velvetshell.sh', VOdir_five, str(sKmer), str(eKmer), five_bam, output_dir, five_assembly])

		#assemble three prime end with VO
		print ' '.join(['./velvetshell.sh', VOdir_three, str(sKmer), str(eKmer), three_bam, output_dir, three_assembly])

		#create database for assemblies if one doesn't already exist
		#check_blast_database(args.assemblies)

		#blast assemblies against contigs
		blastn_cline = NcbiblastnCommandline(query="test_regions.fasta", db=args.assemblies, outfmt="'6 qseqid qlen sacc pident length slen sstart send evalue bitscore'", out="test_regions.txt")
		#stdout, stderr = blastn_cline()
		print blastn_cline()

		#annotate hits to genbank

		#create output table



	#run_command(['bwa mem', args.reference, read1, read2, '>', output_sam])

if __name__ == '__main__':
	main()
