""" ********** getFiles.py **********

Author: Michael Giansiracusa
Email: giansiracumt@ornl.gov

Web Tools Contact: Ranjeet Devarakonda zzr@ornl.gov

Purpose:
    This tool supports downloading files using the ARM Live Data Webservice
Requirements:
    This tool requires python2.7+ or python3.5+, and requests package
"""

import argparse
import json
import requests
import sys
import os
import urllib3
from functools import partial
from multiprocessing import Pool

urllib3.disable_warnings()

HELP_DESCRIPTION = """
*************************** ARM LIVE UTILITY TOOL ***************************************
This tool will help users utilize the ARM Live Data Webservice to download ARM data.
This programmatic interface allows users to query and automate machine-to-machine
downloads of ARM data. This tool uses a REST URL and specific parameters (saveData,
query), user ID and access token, a datastream name, a start date, and an end date,
and data files matching the criteria will be returned to the user and downloaded.

By using this web service, users can setup cron jobs and automatically download data from
/data/archive into their workspace. This will also eliminate the manual step of following
a link in an email to download data. All other data files, which are not on the spinning
disk (on HPSS), will have to go through the regular ordering process. More information
about this REST API and tools can be found at: https://adc.arm.gov/armlive/#scripts

==========================================================================================
To login/register for an access token visit: https://adc.arm.gov/armlive/livedata/home.
==========================================================================================
******************************************************************************************
"""
EXAMPLE = """Example:
python getFiles.py -u userName:XXXXXXXXXXXXXXXX -ds sgpmetE13.b1 -s 2017-01-14 -e 2017-01-20
getARMFiles -u userName:XXXXXXXXXXXXXXXX -ds sgpmetE13.b1 -s 2017-01-14 -e 2017-01-20
"""

def parse_arguments():
    """Parse command line arguments using argparse

    :return:
        Two Namespace object that have an attribute for each command line argument.
        The first return arg contains expected command line flags and arguments.
        The second return arg contains unexpected command line flags and arguments.
    """
    parser = argparse.ArgumentParser(description=HELP_DESCRIPTION, epilog=EXAMPLE,
                                     formatter_class=argparse.RawTextHelpFormatter)
    required_arguments = parser.add_argument_group("required arguments")
    optional_artuments = parser.add_argument_group("optional arguments")

    required_arguments.add_argument("-u", "--user", dest="user", required=True,
                                    help="The user's ARM ID and access token, separated by a colon.\n"
                                         "Obtained from https://adc.arm.gov/armlive/livedata/home")
    required_arguments.add_argument("-ds", "--datastream", dest="datastream", required=True,
                                    help="Name of the datastream. The query service type allows the\n"
                                         "user to enter a DATASTREAM property that's less specific,\n"
                                         "and returns a collection of data files that match the\n"
                                         "DATASTREAM property. For example: sgp30ebbrE26.b1\n")

    optional_artuments.add_argument("-s", "--start", type=str, dest="start",
                        help="Optional; start date for the datastream. "
                             "Must be of the form YYYY-MM-DD")
    optional_artuments.add_argument("-e", "--end", type=str, dest="end",
                        help="Optional; end date for the datastream. "
                             "Must be of the form YYYY-MM-DD")
    optional_artuments.add_argument("-o", "--out", type=str, dest="output", default='',
                        help="Optional; full path to directory where you would like the output\n"
                             "files. Defaults to folder named after datastream in current working\n"
                             "directory.")
    optional_artuments.add_argument("-T", "--test", action="store_true", dest="test",
                        help="Optional; flag that enables test mode. When in test mode only the\n"
                             "query will be run.")
    optional_artuments.add_argument("-D", "--Debug", action="store_true", dest="debug",
                        help="Optional; flag that enables debug printing")
    optional_artuments.add_argument("-p", "--proc", type=int, dest="processes", default=1,
                        help="Optional; Farm work to subprocesses to speed up downloading.\n"
                             "Default=1, Max=24, Increase for faster downloading.")

    if len(sys.argv) <= 1:
        parser.print_help()
        parser.print_usage()
        exit(1)

    cli_args, unknown_args = parser.parse_known_args()

    return cli_args, unknown_args

def main():
    """ main armlive automation script

    :param cli_args:
        A argparse.Namespace object with an attribute for each expected command line argument.
    :return:
        None
    """
    cli_args, unknown_args = parse_arguments()

    # default start and end are empty
    start, end = '', ''
    # start and end strings for query_url are constructed if the arguments were provided
    if cli_args.start:
        start = "&start={}".format(cli_args.start)
    if cli_args.end:
        end = "&end={}".format(cli_args.end)
    # build the url to query the web service using the arguments provided
    if cli_args.test:
        query_url = 'https://armweb-dev.ornl.gov/armlive/livedata/query?user={0}&ds={1}{2}{3}&wt=json'\
         .format(cli_args.user, cli_args.datastream, start, end)
    else:
        query_url = 'https://adc.arm.gov/armlive/livedata/query?user={0}&ds={1}{2}{3}&wt=json'\
         .format(cli_args.user, cli_args.datastream, start, end)

    if cli_args.debug: print("Getting file list using query url:\n\t{0}".format(query_url))
    # get url response, read the body of the message, and decode from bytes type to utf-8 string
    response_body = requests.get(query_url, verify=False).text

    # if the response is an html doc, then there was an error with the user
    if response_body[1:14] == "!DOCTYPE html":
        print("WARNING: Error with user. Check username or token.")
        exit(1)
    # parse into json object
    response_body_json = json.loads(response_body)
    if cli_args.debug: print("response body:\n{0}\n".format(json.dumps(response_body_json, indent=True)))

    # construct output directory
    if cli_args.output:
        # output files to directory specified
        output_dir = os.path.join(cli_args.output)
    else:
        # if no folder given, add datastream folder to current working dir to prevent file mix-up
        output_dir = os.path.join(os.getcwd(), cli_args.datastream)
    # make directory if it doesn't exist
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    # not testing, response is successful and files were returned
    if not cli_args.test:
        num_files = len(response_body_json["files"])
        if response_body_json["status"] == "success" and num_files > 0:
            processes = cli_args.processes if cli_args.processes < 24 else 24
            pool = Pool(processes)
            partial_downloader = partial(downloader, cli_args, output_dir)
            pool.map(partial_downloader, response_body_json['files'])
        else:
            print("WARNING: No files returned or url status error.\n"
                           "Check datastream name, start, and end date.")
    else:
        if cli_args.debug: print("*** Files would have been downloaded to directory:\n----> {}".format(output_dir))


def downloader(cli_args, output_dir, fname):
    output_file = os.path.join(output_dir, fname)
    if os.path.isfile(output_file):
        print("[SKIPPING] {}".format(fname))
        return
    else:
        print("[DOWNLOADING] {}".format(fname))
        # construct link to web service saveData function
        save_data_url = "https://adc.arm.gov/armlive/livedata/saveData?user={0}&file={1}".format(cli_args.user, fname)
        if cli_args.debug: print("Using link: {1}".format(fname, save_data_url))
        # make directory if it doesn't exist
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        # create file and write bytes to file
        with open(output_file, 'wb') as open_file:
            content_bytes = requests.get(save_data_url).content
            if sys.getsizeof(content_bytes) > 200:
                open_file.write(content_bytes)
                print("[DOWNLOADED] {}".format(fname))
            else:
                os.remove(output_file)
                msg = "This data file is not available on /data/archive. To download this file, please an order " \
                      "via Data Discovery. https://adc.arm.gov/discovery"
                print("[ERROR] {}\n{}".format(fname, msg))
        if cli_args.debug: print("file saved to --> {}\n".format(output_file))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exit()

