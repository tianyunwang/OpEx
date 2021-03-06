#!/usr/bin/python

"""
@author: Marton Munz
Last updated: 30.03.2015
"""

# Top-level code of CAVA
###########################################################################################################################################

from __future__ import division
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + '/../../pysamdir')
import pysam

import datetime
import logging
import gzip
from optparse import OptionParser
import basics
from basics import Options
from basics import Record
from data import Ensembl
from data import dbSNP
from data import Reference
import multiprocessing

###########################################################################################################################################

# Printing out welcome meassage
def printStartInfo(ver):
    print "\n-----------------------------------------------------------------------"
    print 'CAVA (Clinical Annotation of VAriants) '+ver+' is now running.'
    print 'Started: ', datetime.datetime.now(),'\n'

# Printing out file names and multithreading info    
def printInputFileNames(copts,options):
	if options.args['outputformat']=='VCF': outfn=copts.output+'.vcf'
	else: outfn=copts.output+'.txt'
	print 'Configuration file:  '+copts.conf
	print 'Input file ('+options.args['inputformat']+'):    '+copts.input
	print 'Output file ('+options.args['outputformat']+'):   '+outfn
	if options.args['logfile']:  print 'Log file:            '+copts.output+'.log'
	if copts.threads>1: 
		print '\nMultithreading:      '+str(copts.threads)+' threads'
	
	if options.args['logfile']: 
		logging.info('Configuration file - '+copts.conf)
		logging.info('Input file ('+options.args['inputformat']+') - '+copts.input)
		if options.args['outputformat']=='VCF': 
			logging.info('Output file ('+options.args['outputformat']+') - '+copts.output+'.vcf')
		else:
			logging.info('Output file ('+options.args['outputformat']+') - '+copts.output+'.txt')
		if copts.threads>1:
			logging.info('Multithreading - '+str(copts.threads)+' threads')
	

# Printing out number of records in the input file
def printNumOfRecords(numOfRecords):
    print '\nInput file contains '+str(numOfRecords)+' records to annotate.\n'

# Initializing progress information
def initProgressInfo():
	sys.stdout.write('\rAnnotating variants ... 0.0%')
	sys.stdout.flush()

# Printing out progress information
def printProgressInfo(counter,numOfRecords):
	x=round(100*counter/numOfRecords,1)
	x=min(x,100.0)
	sys.stdout.write('\rAnnotating variants ... '+str(x)+'%')
	sys.stdout.flush()
	
# Finalizing progress information
def finalizeProgressInfo():
	sys.stdout.write('\rAnnotating variants ... 100.0%')
	sys.stdout.flush()
	print ' - Done.'

# Printing out goodbye message
def printEndInfo(options,copts):
	if options.args['outputformat']=='VCF': outfn=copts.output+'.vcf'
	else: outfn=copts.output+'.txt'
	print '\n(Size of output file: '+str(round(os.stat(outfn).st_size/1000,1))+' Kbyte)'
	print '\nCAVA (Clinical Annotation of VAriants) successfully finished.'
	print 'Ended: ', datetime.datetime.now()
	print "-----------------------------------------------------------------------\n"
	if options.args['logfile']: 
	    logging.info('100% of records annotated.')
	    if not copts.stdout: logging.info('Output file = '+str(round(os.stat(outfn).st_size/1000,1))+' Kbyte')
	    logging.info('CAVA successfully finished.')

# Finding break points in the input file..
def findFileBreaks(inputf,threads):
	ret=[]
	started=False
	counter=0
	for line in open(inputf):
		counter+=1
		line=line.strip()
		if line=='' or line.startswith('#'): continue
		if not started:
			started=True
			first=counter
	delta=int((counter-first+1)/threads)
	for i in range(threads):
		if i<threads-1: ret.append((first+i*delta,first+(i+1)*delta-1))
		else: ret.append((first+i*delta,''))
	return ret

# Reading header from input file
def readHeader(inputfn):
	ret=[]
	for line in open(inputfn):
		line=line.strip()
		if line=='': continue
		if line.startswith("#"): ret.append(line)
		else: break
	return ret

# Merging tmp files to final output file
def mergeTmpFiles(output,format,threads):
	filenames=[]
	for i in range(1,threads+1):
		if format=='VCF': filenames.append(output+'_tmp_'+str(i)+'.vcf')
		else: filenames.append(output+'_tmp_'+str(i)+'.txt')
	
	if format=='VCF': outfn=output+'.vcf'
	else: outfn=output+'.txt'
	
	with open(outfn, 'a') as outfile:	
		for fname in filenames:
			with open(fname) as infile:
				for line in infile:
					outfile.write(line)

	for fn in filenames: os.remove(fn)

###########################################################################################################################################

# Class representing a single annotation process
class SingleJob(multiprocessing.Process):
    
	# Process constructor
	def __init__(self,threadidx,options,copts,startline,endline,genelist,transcriptlist,snplist,impactdir,numOfRecords):
		multiprocessing.Process.__init__(self)
		
		# Thread index
		self.threadidx=threadidx
		
		# Options and command line arguments
		self.options=options
		self.copts=copts
		
		# Start and end line indexes
		self.startline=startline
		self.endline=endline
		
		# Gene, transcript and SNP lists
		self.genelist=genelist
		self.transcriptlist=transcriptlist
		self.snplist=snplist
		
		# Impact defintion directory	
		self.impactdir=impactdir
		
		# Total number of records in the input file
		self.numOfRecords=numOfRecords
		
		# Allowed chromosomes
		self.chroms=['1','2','3','4','5','6','7','8','9','10','11','12','13','14','15','16','17','18','19','20','21','22','X','Y','MT']
		
		# Input file
		if copts.input.endswith('.gz'): self.infile=gzip.open(copts.input,'r')
		else: self.infile=open(copts.input)
		
		# Output file
		if copts.threads>1:
			if options.args['outputformat']=='VCF': outfn=copts.output+'_tmp_'+str(threadidx)+'.vcf'
			else: outfn=copts.output+'_tmp_'+str(threadidx)+'.txt'
			self.outfile=open(outfn,'w')
		else:
			if options.args['outputformat']=='VCF': outfn=copts.output+'.vcf'
			else: outfn=copts.output+'.txt'
			self.outfile=open(outfn,'a')
				
		# Ensembl and dbSNP databases
		if (not options.args['ensembl']=='.') and (not options.args['ensembl']==''): 
			self.ensembl=Ensembl(options)
			if options.args['logfile'] and threadidx==1: logging.info('Connected to Ensembl database.')
		else: self.ensembl=None
		
		if (not options.args['dbsnp']=='.') and (not options.args['dbsnp']==''): 
			self.dbsnp=dbSNP(options)
			if options.args['logfile'] and threadidx==1: logging.info('Connected to dbSNP database.')
		else: self.dbsnp=None
		
		# Reference genome
		self.reference=Reference(options)
		if options.args['logfile'] and threadidx==1: logging.info('Connected to reference genome.')
		
		# Target BED file
		if (not options.args['target']=='.') and (not options.args['target']==''):
			self.targetBED=pysam.Tabixfile(options.args['target'],parser=pysam.asBed())
		else: 
			self.targetBED=None
			
		if not copts.stdout and threadidx==1: initProgressInfo()	
		
	# Running process		
	def run(self):
		if options.args['logfile']: 
		    logging.info('Process '+str(self.threadidx)+' - variant annotation started.')
		
		# Iterating through input file
		counter=0
		thr=10
		for line in self.infile:
			counter+=1
			
			# Considering lines between startline and endline only
			if counter<int(self.startline): continue
			if not self.endline=='':
				if counter>int(self.endline): break
			
			line=line.strip()
			if line=='': continue
           
    		# Printing out progress information
			if not copts.stdout and self.threadidx==1: 
				if counter%1000==0: printProgressInfo(counter,int(self.numOfRecords/self.copts.threads))		   
		   
		    # Parsing record from input file
			record=Record(line,self.options,self.targetBED)
    
		    # Filtering out REFCALL records
			if record.filter=='REFCALL': continue    
    
		    # Filtering record, if required
			if self.options.args['filter'] and not record.filter=='PASS': continue    
    
		    # Only include records of allowed chromosome names
			if record.chrom not in self.chroms: continue
    
		    # Annotating the record based on the Ensembl, dbSNP and reference data
			record.annotate(self.ensembl,self.dbsnp,self.reference,self.impactdir)
    
		    # Writing annotated record to output file
			record.output(self.options.args['outputformat'],self.outfile,self.options,self.genelist,self.transcriptlist,self.snplist,self.copts.stdout)
		
		    # Writing progress information to log file
			if self.threadidx==1 and self.options.args['logfile']:
				x=round(100*counter/int(self.numOfRecords/self.copts.threads),1)
				x=min(x,100.0)
				if x>thr:
					logging.info(str(thr)+'% of records annotated.')
					thr+=10
		
		# Closing output file	
		self.outfile.close()
		
		# Finalizing progreaa info
		if not copts.stdout and  self.threadidx==1: finalizeProgressInfo()
			
    
###########################################################################################################################################

ver='v1.1.1'

# Command line argument parsing
descr='CAVA (Clinical Annotation of VAriants) '+ver+' is a lightweight, fast and flexible NGS variant annotation tool that provides consistent transcript-level annotation.'
epilog='\nExample usage: \npython path/to/cava/cava.py -c config.txt -i input.vcf -o output\n\n(More details in the documentation: cava-'+ver+'-doc.pdf)\n\n'
OptionParser.format_epilog = lambda self, formatter: self.epilog
parser = OptionParser(usage='python path/to/cava/cava.py <options>',version=ver,description=descr,epilog=epilog)
parser.add_option('-i', "--in", default='input.vcf', dest='input', action='store', help="Input file name [default value: %default]")
parser.add_option('-o', "--out", default='output', dest='output', action='store', help="Output file name prefix [default value: %default]")
parser.add_option('-c', "--config", default='config.txt', dest='conf', action='store', help="Configuration file name [default value: %default]")   
parser.add_option('-s', "--stdout", default=False, dest='stdout', action='store_true', help="Write output to standard output [default value: %default]")
parser.add_option('-t', "--threads", default=1, dest='threads', action='store', help="Number of threads [default value: %default]")
(copts, args) = parser.parse_args()
copts.threads=int(copts.threads)
if copts.threads>1: copts.stdout=False

# Reading options from configuration file
options=Options(copts.conf)

# Initializing log file
if options.args['logfile']:
    logging.basicConfig(filename=copts.output+'.log',filemode='w',format='%(asctime)s %(levelname)s: %(message)s', level=logging.DEBUG)

# Printing out version information and start time
if not copts.stdout: printStartInfo(ver)
if options.args['logfile']: logging.info('CAVA '+ver+' started.')

# Checking if options specified in the configuration file are correct
basics.checkOptions(options)

# Printing out configuration, input and output file names
if not copts.stdout: printInputFileNames(copts,options)

# Reading gene, transcript and snp lists from files
genelist=basics.readSet(options,'genelist')
transcriptlist=basics.readSet(options,'transcriptlist')
snplist=basics.readSet(options,'snplist')

# Parsing @impactdef string
if not (options.args['impactdef']=='.' or options.args['impactdef']==''):
	impactdir=dict()
	valuev=options.args['impactdef'].split('|')
	for i in range(len(valuev)):
		classv=valuev[i].split(',')
		for c in classv: impactdir[c.strip()]=str(i+1)
else: impactdir=None

# Counting and printing out number of records of input file
numOfRecords=basics.countRecords(copts.input)
if not copts.stdout: printNumOfRecords(numOfRecords)
if options.args['logfile']: 
    logging.info(str(numOfRecords)+' records to be annotated.')

# Writing header to output file
if options.args['outputformat']=='VCF': outfile=open(copts.output+'.vcf','w')
else: outfile=open(copts.output+'.txt','w')
header=readHeader(copts.input)
basics.writeHeader(options,'\n'.join(header),outfile,copts.stdout)
outfile.close()

# Find break points in the input file
breaks=findFileBreaks(copts.input,copts.threads)

# Initializing annotation processes
threadidx=0
processes = []
for (startline,endline) in breaks:
	threadidx+=1
	processes.append(SingleJob(threadidx,options,copts,startline,endline,genelist,transcriptlist,snplist,impactdir,numOfRecords))

# Running annotation processes
for process in processes: process.start()
for process in processes: process.join()

# Merging tmp files
if copts.threads>1: mergeTmpFiles(copts.output,options.args['outputformat'],copts.threads)

# Printing out summary information and end time
if not copts.stdout: printEndInfo(options,copts)
    
###########################################################################################################################################

