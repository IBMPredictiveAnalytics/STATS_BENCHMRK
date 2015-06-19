"""SPSSbench module for timing command sets
Note that it requires the Pywin32 extensions, which can be found here
http://sourceforge.net/projects/pywin32/"""

#Licensed Materials - Property of IBM
#IBM SPSS Products: Statistics General
#(c) Copyright IBM Corp. 2011, 2014
#US Government Users Restricted Rights - Use, duplication or disclosure 
#restricted by GSA ADP Schedule Contract with IBM Corp.

# Copyright (C) 2005 by SPSS Inc.

helptext = r"""STATS BENCHMRK CMDSET1=filespec [CMDSET2=filespec]
NUMREP=n [PROCESSES=process name list]
/OUTPUT OUTFILE=csv-filespec [STATISTICS=list of statistics]
[/HELP].

Benchmark one or two sets of syntax and report selected resource usage
statistics.

Example:
STATS BENCHMRK CMDSET1="C:\jobs\insert1.sps" 
NUMREP=3  PROCESSES=stats spssengine startx startx32
/OUTPUT OUTFILE="c:\temp\bench.csv" 
STATISTICS=UserTime KernelTime  PageFaultCount PeakWorkingSetSize WorkingSetSize.

This command requires the Python for Windows extensions by Mark Hammond
available from
http://sourceforge.net/projects/pywin32/
Be sure to get the version appropriate for the version of Python required by
Statistics.

CMDSET1 and CMDSET2 specify syntax files to be run repeatedly in
alternation.  CMDSET2 is optional.  Using two command sets is
useful when you have two alternative versions of syntax for the same
task and want to determine which is  more efficient.

NUMREP specifies how many times to run the cmdsets.  For each rep, CMDSET1
is run and then, if given, CMDSET2 is run.

PROCESSES specifies one or more processes to monitor.
Statistics are recorded for each specified process associated with Statistics.
The process names may vary with the Statistics version.  For V20, they are
stats - the Statistics frontend
spssengine - the Statistics backend
startx - the Python process
startx32 - the R process.

The R process must be started before running this command if it is to be
monitored.

OUTFILE names a csv file to contain the benchmark statistics.  Each case
includes process, command set, and repetition identifiers along with each
statistic measured at the start and end of the syntax execution.

STATISTICS lists the statistics to be collected.  Use ALL to get every one.
Otherwise select from this list.  See the Task Manager process help for
definitions.

times:
 CreationTime, UserTime, KernelTime
 Creation time seems often not to be meaningful.
 
memory:
 QuotaPagedPoolUsage, QuotaPeakPagedPoolUsage, QuotaNonPagedPoolUsage,
   PageFaultCount, PeakWorkingSetSize, PeakPagefileUsage, QuotaPeakNonPagedPoolUsage,
   PagefileUsage, WorkingSetSize 
   
i/o:
WriteOperationCount,WriteTransferCount, OtherOperationCount,
    OtherTransferCount, ReadOperationCount, ReadTransferCount
    
/HELP displays this text and does nothing else.
"""

__author__ =  'spss'
__version__=  '2.0.1'

# for recent versions of Statistics
from extension import Template, Syntax, processcmd
import spss
import time, re
try:
    from win32process import GetCurrentProcess, GetProcessMemoryInfo, GetProcessTimes, GetProcessIoCounters
    import win32api, win32pdhutil, win32con
except:
    raise SystemError(_("This module requires the Python for Windows extensions.  It can be downloaded from http://sourceforge.net/projects/pywin32/"))

# process handle can be found with
# hdl=win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, 0, pid)
# win32pdhutil.FindPerformanceAttributesByName("spssengine") returns pid
# i/o: win32process.GetProcessIoCounters(hdl) returns dict of io information
# memory: win32process.GetProcessMemoryInfo(hdl)
# win32process.GetProcessWorkingSetSize(hdl)  (returns duple)
# win32api.CloseHandle(hdl)

class benchstats(object):
    """This class handles benchmark measures and snapshots.  It is Windows specific.
    It monitors the selected Statistics processes, so any overhead from the
    monitoring will be included in the measures.
    """
    memory = [
    'QuotaPagedPoolUsage', 'QuotaPeakPagedPoolUsage', 'QuotaNonPagedPoolUsage',
    'PageFaultCount', 'PeakWorkingSetSize', 'PeakPagefileUsage', 'QuotaPeakNonPagedPoolUsage',
    'PagefileUsage', 'WorkingSetSize']
    time = [
    'CreationTime', 'UserTime', 'KernelTime']
    io = [
    'WriteOperationCount','WriteTransferCount', 'OtherOperationCount',
    'OtherTransferCount', 'ReadOperationCount', 'ReadTransferCount']
    apinames = [GetProcessMemoryInfo, GetProcessTimes,GetProcessIoCounters]
    apilist = [memory, time, io]  # list of lists

    def __init__(self, processes, stats=None):
        if stats is None or "all" in stats:
            self.stats = benchstats.time + benchstats.memory + benchstats.io
        else:
            self.stats = stats
        # readings will be a list of lists of readings: one list for each process
        self.readings = []
        self.measures=["time"]
        self.apis = [time]
        
        # build list of calls for specified measures
        # must match ignoring case but set the cased version of the statistic name
        for s in self.stats:
            for i, api in enumerate(benchstats.apilist):
                cased_s = caselessin(s, api)
                if cased_s:
                    self.measures.append(cased_s)
                    self.apis.append(benchstats.apinames[i])
                    break
            else:
                raise ValueError(_("Invalid measure: %s") % s)
            
        # find the processes to monitor - they must already exist
        self.handles = []
        self.procfound = []
        self.processes = []
        for p in processes:
            # this api is slow
            pnum = win32pdhutil.FindPerformanceAttributesByName(p)
            if len(pnum) > 1 and p.lower() in ["stats", "spssengine", "statisticsb"]:
                raise SystemError(_("""There are multiple instances of Statistics running.  Only one can be running when monitoring: %s""" % p))
            for instance in pnum:
                self.handles.append(win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, 0, instance))
                pid = p + "-" + str(instance)
                self.processes.append(pid)
                self.readings.append([])
        if len(self.processes) == 0:
            raise ValueError(_("""No instances of any of the specified processes were found"""))
        else:
            print "Processes to be monitored: " + ",".join(self.processes)
            
    def snap(self, rep, group):
        """record new set of statistics measures for designated group and selected processes
        One record for each process monitored
        
        rep is the repetition number
        group is the cmdset number (1 or 2)
        """

        for j, p in enumerate(self.processes):
            r = [group, rep]
            for i in range(len(self.measures)):
                if self.measures[i] == "time":
                    r.append(time.time())   # current time in seconds
                else:
                    r.append(float(self.apis[i](self.handles[j])[self.measures[i]]))
            self.readings[j].append((p, r))

    def getrow(self, mergecount=1):
        """generator for sets of snap measures.  It yields the next complete row of snaps.

        mergecount specifies the number of
        snaps to be combined to make a complete observation.  If snapping before and after some
        events, for example, mergecount should be 2."""

        for pn in range(len(self.processes)):
            for rows in range(0, len(self.readings[pn]), mergecount):
                row = str(self.readings[pn][rows][0])+ " " \
                    + str([self.readings[pn][rows+i][1:] for i in range(mergecount)])
                yield re.sub(r"[][(),L]", "", row) + "\n"

    def save(self, filespec, sets=[""]):
        """write measures to specified file in a form suitable for reading into Statistics.
        
        sets is a list of strings to append to the generated variable names.  Its length
        determines how readings are paired.  If the length is two, for example, there will
        be 2 times the number of statistics in each row with the names suffixed by the
        strings given.  The size of sets determines how many (sequential) snaps are
        concatenated to give each output record.

        For example:
        bstat.save(file, sets=["Start", "Stop"])
        would save a set of before and after measures for the selected statistics with
        Start and Stop appended to the pairs of variable names.
        """
        
        for p in self.handles:
            win32api.CloseHandle(p)

        f = open(filespec, "w")
#   construct variable names heading
        namelist = ["Process"]
        for g, s in enumerate(sets):
            namelist.append("Cmdset" + str(g))
            namelist.append("Repetition" + str(g))
            for i in range(len(self.measures)):
                namelist.append(self.measures[i] + s)   
        f.write(" ".join(namelist)+"\n")

        for row in self.getrow(mergecount=len(sets)):
            f.write(row)
        f.close()

def caselessin(needle, haystack):
    """Find needle in haystack ignoring case and return haystack item or None
    
    needle is the item to find
    haystack is a list of matches"""
    
    needle = needle.lower()
    for item in haystack:
        if needle == item.lower():
            return item
    else:
        return None

def benchmark(outfile, cmdset1, cmdset2=None, stats=None, processes=None, numrep=1):
    """Benchmark repetitions of one or more commands against, optionally, an alternative set.
    
    When there are two sets, the repetitions are interleaved.
    numrep is the repetition count.
    cmdset1 and cmdlist 2 are lists of commands to be timed.  Remember to include
    an EXECUTE if you are timing transformation commands that would not otherwise
    generate a data pass.
    stats is a list of statistics to be collected or ALL.
    processes is a list of the Statistics processes to monitor.  All are assumed by
    default, but only one Statistics product session can be running.  Process names
    vary some by Statistics version.
    
    outfile specifies a file to get the individual results for the specified measures in a csv format
    suitable for reading into Statistics. Variable names are written on the first line.
    """
    
    # debugging
    # makes debug apply only to the current thread
    #try:
        #import wingdbstub
        #if wingdbstub.debugger != None:
            #import time
            #wingdbstub.debugger.StopDebug()
            #time.sleep(2)
            #wingdbstub.debugger.StartDebug()
        #import thread
        #wingdbstub.debugger.SetDebugThreads({thread.get_ident(): 1}, default_policy=0)
        ## for V19 use
        ##    ###SpssClient._heartBeat(False)
    #except:
        #pass
        
    numsets = cmdset2 and 2 or 1
    processnames = set(["spssengine", "stats", "startx", "startx32"])
    if processes is None:
        processes = processnames
    #     bstat is a benchstats object containing the statistics to be collected.
    bstat = benchstats(processes, stats)
    cmd1 = """INSERT FILE="%(cmdset1)s".""" % locals()
    cmd2 = """INSERT FILE="%(cmdset2)s".""" % locals()  # run only if cmdset2 not null
    
    # Run one or two command files repeatedly generating before and after resource
    # records per process for each repetition
    
    for i in range(numrep):
        bstat.snap(i, group=1)     #start
        spss.Submit(cmd1)
        bstat.snap(i, group=1)     #stop
        if cmdset2:
            bstat.snap(i, group=2) #start
            spss.Submit(cmd2)
            bstat.snap(i, group=2) #stop

    bstat.save(outfile, sets=["Start", "Stop"])


def Run(args):
    """Execute the STATS BENCHMRK extension command"""

    args = args[args.keys()[0]]

    oobj = Syntax([
        Template("CMDSET1", subc="",  ktype="literal", var="cmdset1"),
        Template("CMDSET2", subc="",  ktype="literal", var="cmdset2"),
        Template("OUTFILE", subc="OUTPUT", ktype="literal", var="outfile"),
        Template("NUMREP", subc="", ktype="int", var="numrep",
            vallist=[1]),
        Template("PROCESSES", subc="", ktype="str", var="processes", islist=True,
            vallist=["spssengine", "stats", "startx", "startx32", "statisticsb"]),
        Template("STATISTICS", subc="OUTPUT", ktype="str", var="stats", islist=True),
        Template("HELP", subc="", ktype="bool")])
        
    #enable localization
    global _
    try:
        _("---")
    except:
        def _(msg):
            return msg
    # A HELP subcommand overrides all else
    if args.has_key("HELP"):
        #print helptext
        helper()
    else:
        processcmd(oobj, args, benchmark)

def helper():
    """open html help in default browser window
    
    The location is computed from the current module name"""
    
    import webbrowser, os.path
    
    path = os.path.splitext(__file__)[0]
    helpspec = "file://" + path + os.path.sep + \
         "markdown.html"
    
    # webbrowser.open seems not to work well
    browser = webbrowser.get()
    if not browser.open_new(helpspec):
        print("Help file not found:" + helpspec)
try:    #override
    from extension import helper
except:
    pass