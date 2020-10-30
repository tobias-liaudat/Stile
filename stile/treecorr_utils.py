"""
treecorr_utils.py: Contains elements of Stile needed to interface with Mike Jarvis's TreeCorr
program.
"""
import numpy
from . import file_io
import treecorr
from treecorr.corr2 import corr2_valid_params


def Parser():
    import argparse
    p = argparse.Parser()
    p.add_argument('--file_type',
                   help="File type (ASCII or FITS)",
                   dest='file_type')
    p.add_argument('--delimiter',
                   help="ASCII file column delimiter",
                   dest='delimiter')
    p.add_argument('--comment_marker',
                   help="ASCII file comment-line marker",
                   dest='comment_marker')
    p.add_argument('--first_row',
                   help="First row of the file(s) to be considered",
                   dest='first_row')
    p.add_argument('--last_row',
                   help="Last row of the file(s) to be considered",
                   dest='last_row')
    p.add_argument('--x_units',
                   help="X-column units (radians, hours, degrees, arcmin, arcsec) -- only allowed "+
                        "by certain DataHandlers",
                   dest='x_units')
    p.add_argument('--y_units',
                   help="Y-column units (radians, hours, degrees, arcmin, arcsec) -- only allowed "+
                        "by certain DataHandlers",
                   dest='y_units')
    p.add_argument('--ra_units',
                   help="RA-column units (radians, hours, degrees, arcmin, arcsec) -- only "+
                        "allowed by certain DataHandlers",
                   dest='ra_units')
    p.add_argument('--dec_units',
                   help="dec-column units (radians, hours, degrees, arcmin, arcsec) -- only "+
                        "allowed by certain DataHandlers",
                   dest='dec_units')
    p.add_argument('--flip_g1',
                   help="Flip the sign of g1 [default: False]",
                   dest='flip_g1', default=False)
    p.add_argument('--flip_g2',
                   help="Flip the sign of g2 [default: False]",
                   dest='flip_g2', default=False)
    p.add_argument('--min_sep',
                   help="Minimum separation for the TreeCorr correlation functions",
                   dest='min_sep')
    p.add_argument('--max_sep',
                   help="Maximum separation for the TreeCorr correlation functions",
                   dest='max_sep')
    p.add_argument('--nbins',
                   help="Number of bins for the TreeCorr correlation functions",
                   dest='nbins')
    p.add_argument('--bin_size',
                   help="Bin width for the TreeCorr correlation functions",
                   dest='bin_size')
    p.add_argument('--sep_units',
                   help="Units for the max_sep/min_sep/bin_size arguments for the TreeCorr "+
                        "correlation functions",
                   dest='sep_units')
    p.add_argument('--bin_slop',
                   help="A parameter relating to accuracy of the TreeCorr bins--changing is not "+
                        "recommended",
                   dest='bin_slop')
    p.add_argument('-v', '--verbose',
                   help="Level of verbosity",
                   dest='verbose')
    p.add_argument('--num_threads',
                   help='Number of threads (TreeCorr) or multiprocessing.Pool processors '+
                        '(Stile) to use; default is to automatically determine',
                   dest='num_threads')
    p.add_argument('--split_method',
                   help="One of 'mean', 'median', or 'middle', directing TreeCorr how to split the "
                        "tree into child nodes. [default: 'mean']",
                   dest='split_method')
    return p


def ReadTreeCorrResultsFile(file_name):
    """
    Read in the given ``file_name``.  Cast it into a formatted numpy array with the appropriate
    fields and return it.

    :param file_name: The location of an output file from TreeCorr.
    :returns:         A numpy array corresponding to the data in ``file_name``.
    """
    from . import stile_utils
    output = file_io.ReadASCIITable(file_name, comments='#')

    if not len(output):
        raise RuntimeError('File %s (supposedly an output from TreeCorr) is empty.'%file_name)
    # Now, the first line of the TreeCorr output file is of the form:
    # "# col1 . col2 . col3 [...]"
    # so we can get the proper field names by reading the first line of the file and processing it.
    with open(file_name) as f:
        DEPRECIATED_fields = f.readline().split() # [TL] BUG FIX
        fields = f.readline().split()   # [TL] Need to read into the 2nd line of the file to recover the actual fields
                                        # The first line contains:
                                        # ['##', "{'coords':", "'spherical',", "'metric':", "'Euclidean',",
                                        # "'sep_units':", "'arcmin',", "'bin_type':", "'Log'}"]
    fields = fields[1:]
    fields = [field for field in fields if field != '.']
    return stile_utils.FormatArray(output, fields=fields)


def PickTreeCorrKeys(input_dict):
    """
    Take an ``input_dict``, harvest the kwargs you'll need for TreeCorr, and return a dict
    containing these values.  This is useful if you have a parameters dict that contains some things
    TreeCorr might want, but some other keys that shouldn't be used by it.

    :param input_dict: A dict containing some (key, value) pairs that apply to TreeCorr.
    :returns:          A dict containing the (key, value) pairs from input_dict that apply to
                       TreeCorr.
    """
    if not input_dict:
        return {}
    if 'treecorr_kwargs' in input_dict:
        treecorr_dict = input_dict['treecorr_kwargs']
    else:
        treecorr_dict = {}
    for key in corr2_valid_params:
        if key in input_dict:
            treecorr_dict[key] = input_dict[key]
    return treecorr_dict
