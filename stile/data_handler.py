"""
data_handler.py: defines the classes that serve data to the various Stile systematics tests in the
default drivers.
"""
import os
import glob
import copy
import stile_utils
from .binning import BinStep, BinList, ExpandBinList
from .file_io import ReadASCIITable, ReadFITSTable, ReadFITSImage, ReadTable, ReadImage
from . import sys_tests

class DataHandler:
    """
    A class which contains information about the data set Stile is to be run on.  This is used for
    the default drivers, not necessarily the pipeline-specific drivers (such as HSC/LSST).

    The class needs to be able to do four things:
     1. List all the formats for which it has data (DataHandler.listFileTypes()).  A "format"
        consists of an epoch, an extent, and a data format as follows:
         -- epoch: whether this is a single/coadd (ie no time-series information) catalog, or a
              multiepoch time series.
         -- extent: "CCD", "field", "patch" or "tract".  "CCD" should be a CCD-type dataset, "field"
              a single pointing/field-of-view, "patch" an intermediate-size area, and "tract" a
              large area.  (These terms have specific meanings in the LSST pipeline, but are used
              for convenience here.)
         -- data_format: "image" or "catalog."  Right now no image-level tests are implemented but
              we request this kwarg for future development.
        These can be given as three kwargs, or a single hyphen-spliced string.  That is, the call
        signature can be:
            DataHandler.listFileTypes('single', 'field', 'catalog')
            DataHandler.listFileTypes('single-field-catalog')
        If you don't want to keep track of the order, you can create a stile.Format object in your
        calling function:
            stile.Format(epoch='single', extent='field', data_format='catalog')
        and use that object as the argument for all these functions instead.
     2. List all the object types for a given format (DataHandler.listObjects()).  Formats are as
        defined above; the object type is a string, and should at least be able to handle all the
        object types given in stile_utils.object_types.
     3. List some data given a format and an object type or object types(DataHandler.listData()).
        The format and object_type are as defined above, except that here an object type may be
        a list of strings rather than a single string; if a list, then the returned data should
        consist of pairs/triplets/etc of data files that should be analyzed together.  For example,
        if the object_types argument is ['star', 'galaxy'], the returned list of data might consist
        of pairs of star and galaxy catalogs from the same CCD.
      - Take an element of the data list from DataHandler.listData() and retrieve it for use
        (DataHandler.getData()), optionally with bins defined.  (Bins can also be defined on a test-
        by-test basis, depending on which format makes the most sense for your data setup.)

      Additionally, the class can define a .getOutputPath() function to place the data in a more
      complex system than the default (all in one directory with long output path names).
      """
    multi_file = True
    clobber = False
    written_files = []
    output_path = '.'

    def __init__(self):
        raise NotImplementedError()

    def listData(self, object_types, epoch, extent, data_format, required_fields=None):
        raise NotImplementedError()

    def getData(self, ident, object_types=None, epoch=None, extent=None, data_format=None,
                bin_list=None):
        """
        Return some data matching the `ident` for the given kwargs.  This can be a numpy array, a
        tuple (file_name, field_schema) for a file already existing on the filesystem, or a list of
        either of those things.

        If it's a tuple (file_name, field_schema), the assumption is that it can be read by a simple
        FITS or ASCII reader.  The format will be determined from the file extension.
        """
        raise NotImplementedError()

    def getOutputPath(self, *args):
        """
        Return a path to an output file given a list of strings that should appear in the output
        filename, taking care not to clobber other files (unless requested).
        @param args       A list of strings to appear in the file name
        @returns A path to an output file meeting the input specifications.
        """
        #TODO: no-clobbering case
        if args[-1][0]=='.':
            sys_test_string = '_'.join(args[:-1])
            extension = args[-1]
        else:
            sys_test_string = '_'.join(args)
            extension = ''
        if self.clobber and self.multi_file:
            file_base = os.path.join(self.output_path, sys_test_string+extension)
            if file_base not in self.written_files:
                self.written_files[file_base] = 0
            else:
                self.written_files[file_base] += 1
            return os.path.join(self.output_path,
                                sys_test_string+'_'+str(self.written_files[file_base])+extension)
        elif self.multi_file:
            files = glob.glob(os.path.join(self.output_path, sys_test_string)+'*'+extension)
            n_underscores = self.output_path.count('_')+sys_test_string.count('_')+1
            files = [f for f in files if f.count('_')<=n_underscores]  # Ignore filenames with bins
            if files:
                if not os.path.join(self.output_path, sys_test_string)+extension in files:
                    return os.path.join(self.output_path, sys_test_string+extension)
                elif not os.path.join(self.output_path,
                                      sys_test_string+'_'+str(len(files))+extension) in files:
                    return os.path.join(self.output_path,
                                        sys_test_string+'_'+str(len(files))+extension)
                else:
                    for i in range(len(files)):
                        if not os.path.join(self.output_path,
                                            sys_test_string+'_'+str(len(files))+extension) in files:
                            return os.path.join(self.output_path,
                                                sys_test_string+'_'+str(len(files))+extension)
            else:
                return os.path.join(self.output_path, sys_test_string+extension)
        else:
            return os.path.join(self.output_path, sys_test_string+extension)

class ConfigDataHandler(DataHandler):
    """
    A DataHandler to read in, parse, and prepare a set of data and sys_tests from a YAML or JSON
    config file.  The class must be initialized with a dict or filename (or list of filenames).
    It then generates two class attributes, .files and .sys_tests.  Each is a dict, described below.
    It also generates a .groups attribute, a dict that matches up elements from the .files dict that
    can be analyzed together (for eg a test that needs both stars and galaxies in the same region of
    sky), also described below.
    
    This class is designed to be used with the ConfigDriver (found in driver.py) to actually run the
    described tests.  Be aware that this function removes keys from the dict it takes as input.

    The .files and .sys_tests are dicts keyed by a "format" (a string of the form 
    "epoch-extent-dataFormat").  The values of the dict for the .files attribute are also dicts,
    keyed by the object type, with values being lists of files (either strings or dicts giving more
    info about how to read in the file); the values of the .sys_tests dict are just lists of tests,
    all of them defined by a dict of the form {'sys_test': SysTest object, 'extra_args': extra
    keyword arguments to be passed in calls to the SysTest object, 'bins': list of bins to be
    applied to the data}.  (The 'bins' option is not currently allowed for tests that require more
    than one data set to run.)   Or, visually:
    self.files = {'format_1': {
                    'object_type_1': [file_1, file_2, {dict_describing_file_3}, ...],
                    'object_type_2': [file_4]}, ...}
    self.sys_tests = {'format_1': 
                        [{'sys_test': test_object_1, 'extra_args': {}, 'bins': [bin1, bin2...]}]}
                        
    The .groups attribute is slightly different.  It is keyed by a group name, and then proceeds
    through format and object_type to an index into the corresponding .files[format][object_type]
    list, as follows:
    self.groups = {'group_1': {
                        'format_1': {
                            'object_1': index_1,
                            'object_2': index_2} } }
    """
    # Keys we expect to get in 'test' or 'bin' dictionaries
    expected_systest_keys = {
        'CorrelationFunction': ['name', 'bins', 'type', 'treecorr_kwargs', 'extra_args'],
        'ScatterPlot': ['name', 'bins', 'type', 'extra_args'],
        'WhiskerPlot': ['name', 'bins', 'type', 'extra_args'],
        'Stat': ['name', 'bins', 'field', 'object_type', 'extra_args']
    }
    expected_bin_keys = {
        'List': ['name', 'field', 'endpoints'],
        'Step': ['name', 'field', 'low', 'high', 'step', 'n_bins', 'use_log']
    }

    def __init__(self, stile_args):
        if 'config_file' in stile_args:
            config = self.loadConfig('config_file')
            config.update(stile_args)
            stile_args = config
        elif isinstance(stile_args, (str,list)):
            stile_args = self.loadConfig(stile_args)
            config = stile_args
        elif isinstance(stile_args, dict):
            config = stile_args
        else:
            raise ValueError("Input cannot be used to initalize a ConfigDataHandler: "+
                             str(stile_args))
        self.parseFiles(config)
        self.parseSysTests(config)
        self.output_path = stile_args.get('output_path', '.')
        self.clobber = stile_args.get('clobber', False)
        self.stile_args = stile_args

    def loadConfig(self, files):
        """
        Read in a config file or a list of config files.  If a list, condense into one config dict,
        with later config files taking precedence over earlier config files.
        """
        try:
            import yaml as config_reader
            has_yaml=True
        except:
            import json as config_reader
            has_yaml=False
        if isinstance(files, str):
            try:
                with open(files) as f:
                    config = config_reader.load(f)
            except Exception as e:
                if not has_yaml and os.path.splitext(files)[-1].lower()=='.yaml':
                    raise ValueError('It looks like this config file is a .yaml file, but you '+
                                     "don't seem to have a working yaml module: %s"%files)
                else:
                    raise e
        elif hasattr(files, '__iter__'):
            config_list = []
            for file_name in files:
                with open(file_name) as f:
                    config_list.append(config_reader.load(f))
            config = config_list[0]
            for config_item in config_list[1:]:
                config.update(config_item)
        return config

    def parseSysTests(self, stile_args):
        """
        Process the arguments from the config file/command line that tell Stile which tests to do.
        Needs to be done after parseFiles, since it uses the dictionary built up by parseFiles as a
        base for the test dictionary.
        """
        self.parseSysTestsDict(stile_args)
        self.sys_tests = {}
        for format in self.sys_tests_dict:
            self.sys_tests[format] = [self.makeTest(s) for s in self.sys_tests_dict[format]]
        return self.sys_tests

    def parseSysTestsDict(self, stile_args):
        """
        Process the arguments from the config file/command line that tell Stile which tests to do,
        as far as a formatted dict of dicts (turning the dicts into SysTest objects is done by
        parseSysTests, which generally calls this function).
        """
        self.sys_tests_dict = {}
        for format in self.files:
            self.sys_tests_dict[format] = []
        keys = sorted(stile_args.keys())
        for key in keys:
            # Pull out the sys_test arguments and process them
            if key[:8]=='sys_test':
                sys_test_obj = stile_args.pop(key)
                if isinstance(sys_test_obj, dict) and not 'name' in sys_test_obj:
                    # This is a nested dict, so recurse it, then add to the sys_test dict
                    sys_test_list = self._recurseDict(sys_test_obj, require_format_args=False)
                    for sys_test in sys_test_list:
                        self.addItem(sys_test, self.sys_tests_dict)
                elif isinstance(sys_test_obj, dict):
                    # otherwise, add directly
                    self.addItem(sys_test_obj, self.sys_tests_dict)
                elif hasattr(sys_test_obj, '__iter__'):
                    for sys_test in sys_test_obj:
                        if isinstance(sys_test, dict):
                            self.addItem(sys_test, self.sys_tests_dict)
                        else:
                            raise ValueError('Sys_test items in config file which are lists must '+
                                             'contain only dicts')
                else:
                    raise ValueError('Sys_test items in config file must be dicts or lists of'+
                                     'dicts')
        return self.sys_tests_dict # Return for checking purposes, mainly

    def parseFiles(self, stile_args):
        """
        Process the arguments from the config file/command line that tell Stile which data files
        to use and how to use them.
        """
        # Get the 'group' and 'wildcard' keys at the file level, which indicate whether to try to
        # match star & galaxy etc files or to expand wildcards in filenames.
        group = stile_args.get('group', True)  # we don't PopAndCheck here since could be any ID
        if 'group' in stile_args:
            del stile_args['group']
        wildcard = stile_utils.PopAndCheckFormat(stile_args, 'wildcard', bool, default=False)
        keys = sorted(stile_args.keys())
        file_list = []
        n = 0
        for key in keys:
            # Pull out the file arguments and process them
            if key[:4]=='file' and key!='file_reader':
                file_obj = stile_args.pop(key)
                new_file_list, n = self._parseFileHelper(file_obj, start_n=n)
                file_list.append(new_file_list)
        # Now, update the file list with global arguments if lower levels didn't already override
        # them
        fields = stile_utils.PopAndCheckFormat(stile_args, 'fields', (list, dict), default=[])
        if fields:
            file_list = self.addKwarg('fields', fields, file_list)
        flag_field = stile_utils.PopAndCheckFormat(stile_args, 'flag_field', (str, list, dict),
                                                   default=[])
        if flag_field:
            # Flag_fields we want to add together, not just replace (so you can eg cut out all
            # your photometric failures, then define all the "galaxy" files as needing flag=1
            # and all your "star" files as needing flag=0 if they're in the same catalogs on disk.
            file_list = self.addKwarg('flag_field', flag_field, file_list, append=True)
        file_reader = stile_utils.PopAndCheckFormat(stile_args, 'file_reader', (str, dict),
                                                    default='')
        if file_reader:
            file_list = self.addKwarg('file_reader', file_reader, file_list)
        # Clean up the grouping keywords and group names
        self.files, self.groups = self._fixGroupings(file_list)
        return self.files, self.groups # Return for checking purposes, mainly

    def _parseFileHelper(self, files, start_n=0):
        # Recurse through all the levels of the current file arg and turn a nested dict into a
        # list of dicts.
        if isinstance(files, dict):
            # This is a nested dict, so recurse down through it and turn it into a list of dicts
            # instead.
            files = self._recurseDict(files)
        else:
            # If it's already a list, check that it's a list of dicts
            if not hasattr(files, '__iter__'):
                raise ValueError('file config keyword must be a list or dict: got %s of type %s'%(
                                    files, type(files)))
            for file in files:
                if not isinstance(file, dict):
                    raise ValueError('If file parameter is a list, each element must be a dict.  '+
                        'Got %s of type %s instead.'%(file, type(file)))
                # We don't group lists unless specifically instructed, so set that keyword
                file['group'] = file.get('group', False)
        # Now run through the list of dicts that we've created, check all the formats are right,
        # and expand any wildcards.
        for item in files:
            # Check for proper formatting and all relevant keywords, plus expand wildcards if
            # requested
            if not isinstance(item, dict):
                raise ValueError('Expected a list of dicts. Either the config file was in error, '
                                 'or the Stile processing failed.  Current state of "files" '
                                 'argument: %s, this item type: %s'%(files, type(item)))
            format_keys = ['epoch', 'extent', 'data_format', 'object_type']
            if not all([format_key in item for format_key in format_keys]):
                raise ValueError('Got file item %s missing one of the required format keywords %s'%
                                    (item, format_keys))
            item['name'] = self._expandWildcard(item)
        # Clean up formatting and group these files, if applicable
        return_list, n = self._group(files, start_n)
        return_val = self._formatFileList(return_list)
        return return_val, n

    def _recurseDict(self, files, require_format_args=True, **kwargs):
        """
        Recurse through a dictionary of dictionaries (of dictionaries...) contained in the first
        arg, called here "files" although it can be any kind of object.  The kwargs are keys from
        a higher level of the dict which should be included in all lower-level items unless
        overridden by the lower levels explicitly.  Return a list of dicts.

        Set require_format_args to False if the argument "files" doesn't need to have a complete
        list of all format keys for each element, eg if this is being used to define sys_tests
        instead of files.
        """
        # This is a very long and annoying function.  The basic idea of this is to take a possibly
        # nested dict and turn it into a list of dicts, where the keys from higher levels of the
        # dict have been turned into the VALUES of something in the new dict (based on what Stile
        # knows about what kinds of keys those values should correspond to).  That way, we can have
        # arbitrary ordering of levels of the nested dict, while easily maintaining all the
        # information that was put in.  If I was writing this again I'd probably do it differently,
        # frankly, but this works so I'm not messing with it any more.
        #
        # What happens is, if this is a dict, we pull out the kwargs that could apply to child
        # levels of the dict (such as file_reader, etc).  Then we figure out what kind of file-
        # relevant keys are in this layer of the dict.  We pop those keys out of the dict, add them
        # as kwargs to be passed to a recursive call of this function, and then execute the
        # recursive call with the value of the key, along with any kwargs which were passed to this
        # iteration of this function.  (In other words, any kwargs will override previous kwargs
        # [except for 'flag_field' which appends], but we copy the dict to make sure it's not
        # changed for any parallel recursive calls.)  Then, when we get all the way down to a list
        # of dicts, we add all of those kwargs to each element of the list and return that.  Whew!

        format_keys = ['epoch', 'extent', 'data_format', 'object_type']
        # First things first: if this is a list, we've recursed through all the levels of the dict.
        # The kwargs contain the format keys from all the superior levels, so we'll update with
        # the things contained in this list and return a list of dicts that isn't nested any more.
        if isinstance(files, list):
            if not kwargs: # This means it's a top-level list of dicts and shouldn't be grouped
                for file in files:
                    file['group'] = file.get('group', default=False)
                return files
            elif (any([format_key in kwargs for format_key in format_keys]) or
                  require_format_args is False):
                if kwargs.get('epoch')=='multiepoch':
                    # Multiepoch files come in a set, so we can't turn them into single items the
                    # way we do with coadds & single epoch files.
                    if isinstance(files, dict):
                        # Copy the kwargs, then update with the stuff in this dict (which should
                        # override higher levels).
                        if any([format_key in files and format_key in kwargs
                                for format_key in format_keys]):
                            raise ValueError("Duplicate definition of format element for item "+
                                             str(files))
                        elif any([format_key not in files and format_key not in kwargs
                                  for format_key in format_keys]):
                            raise ValueError("Incomplete definition of format for item %s"%files)
                        pass_kwargs = copy.deepcopy(kwargs)
                        pass_kwargs.update(files)
                    elif isinstance(files, (list, tuple)):
                        # Okay.  It's a list of files.  If each item of the list is itself iterable,
                        # then we can split the list up; if none of them are iterable, it's a set
                        # that should be analyzed together.  Anything else is an error.
                        iterable = [hasattr(item, '__iter__') for item in files]
                        if all(iterable):
                            return_list = []
                            for item in files:
                                if isinstance(item, dict):
                                    if any([format_key in item and format_key in kwargs
                                            for format_key in format_keys]):
                                        raise ValueError("Duplicate definition of format element "+
                                                         "for item %s"%item)
                                    elif (isinstance(item, dict) and
                                          any([format_key not in item and format_key not in kwargs
                                               for format_key in format_keys]) and
                                          require_format_args):
                                        raise ValueError("Incomplete definition of format for "+
                                                         "item %s"%item)
                                else:
                                    if not all([format_key in kwargs
                                                for format_key in format_keys]):
                                        raise ValueError("Incomplete definition of format for "+
                                                         "item %s"%item)
                                pass_kwargs = copy.deepcopy(kwargs)
                                if isinstance(item, dict):
                                    pass_kwargs.update(item)
                                else:
                                    if not all([format_key in kwargs
                                                for format_key in format_keys]):
                                        raise ValueError("Incomplete definition of format for "+
                                                         "item %s"%item)
                                    pass_kwargs['name'] = item
                                return_list.append(pass_kwargs)
                            return return_list
                        elif any(iterable):
                            raise ValueError('Cannot interpret list of items for multiepoch: '+
                                             str(files)+'. Should be an iterable, or an iterable '+
                                             'of iterables.')
                        else:
                            pass_kwargs.update({'name': files})
                            return [pass_kwargs]
                    else:
                        raise ValueError('Cannot interpret list of items for multiepoch: '+
                                          files+'. Should be an iterable, or an iterable of '+
                                         'iterables.')
                else:
                    # This one's easier, just loop through if the file list is iterable or else
                    # return the item.
                    return_list = []
                    for file in files:
                        pass_kwargs = copy.deepcopy(kwargs)
                        if isinstance(file, dict):
                            if any([format_key in file and format_key in kwargs
                                    for format_key in format_keys]):
                                raise ValueError("Duplicate definition of format element for item"+
                                                 str(item))
                            elif (isinstance(file, dict) and
                                  any([format_key not in file and format_key not in kwargs
                                       for format_key in format_keys]) and require_format_args):
                                raise ValueError("Incomplete definition of format for item %s"%file)
                            pass_kwargs.update(file)
                        else:
                            if not all([format_key in kwargs for format_key in format_keys]):
                                raise ValueError("Incomplete definition of format for item %s"%file)
                            pass_kwargs['name'] = file
                        return_list += [pass_kwargs]
                    return return_list
            else:
                raise ValueError('File description does not include all format keywords: %s, %s'%(
                                 files, kwargs))

        elif not isinstance(files, dict):
            # This indicates an error, but we can be more specific about which kind of error
            # outside of this function, so just pass the incorrect thing along for now.
            pass_kwargs = copy.deepcopy(kwargs)
            pass_kwargs['name'] = files
            return pass_kwargs
        # We didn't hit either of the previous "if" statements, so this is a dict.
        return_list = []
        pass_kwargs = copy.deepcopy(kwargs)

        # First check for the variables that control how we interpret the items in a given format.
        # We can't just pass_kwargs[key] = PopAndCheckFormat because we want to distinguish cases
        # where we are explicitly given False (which can override higher-level Trues) and cases
        # where we would input False by default (which can't override).
        if 'group' in files:
            pass_kwargs['group'] = files.pop('group') # No checking format here--too many options
        if 'wildcard' in files:
            pass_kwargs['wildcard'] = stile_utils.PopAndCheckFormat(files, 'wildcard', bool)
        if 'fields' in files:
            pass_kwargs['fields'] = stile_utils.PopAndCheckFormat(files, 'fields', (dict, list))
        if 'flag_field' in files:
            if 'flag_field' in pass_kwargs:
                pass_kwargs['flag_field'] = [pass_kwargs['flag_field'], files.pop('flag_field')]
            else:
                pass_kwargs['flag_field'] = stile_utils.PopAndCheckFormat(files, 'flag_field',
                                                                          (str, list, dict))
        if 'file_reader' in files:
            pass_kwargs['file_reader'] = files.get('file_reader')

        # Now, if there are format keywords, recurse through them, removing the keys as we go.
        keys = files.keys()
        for format_name, default_vals in zip(format_keys,
                                 [stile_utils.epochs, stile_utils.extents,
                                  stile_utils.data_formats, stile_utils.object_types]):
            if any([key in default_vals for key in keys]):  # any() so users have the ability to
                if format_name in kwargs:                   # arbitrarily define eg extents
                    raise ValueError("Duplicate definition of %s: already have %s, "
                                     "requesting %s"%(format_name, kwargs[format_name], keys))
                for key in keys:
                    new_files = files.pop(key)
                    pass_kwargs[format_name] = key
                    return_list += self._recurseDict(new_files,
                                                     require_format_args = require_format_args,
                                                     **pass_kwargs)
        # If there are keys left, it might be a single dict describing one file; check for that.
        if files:
            if 'name' in files:
                if (all([format_key in files or format_key in kwargs for format_key in format_keys])
                    or require_format_args==False):
                    if any([format_key in files and format_key in kwargs
                            for format_key in format_keys]):
                        raise ValueError("Duplicate format definition for item %s"%str(files))
                    pass_kwargs.update(files)
                    return_list+=[pass_kwargs]
                    files_keys = files.keys()
                    for key in files_keys:
                        del files[key]
                else:
                    raise ValueError('File description does not include all format keywords: '+
                                     '%s'%files)
            else:
                raise ValueError("Unprocessed keys found: %s"%files.keys())
        return return_list

    def _expandWildcard(self, item):
        #  Expand wildcards in a file list
        if isinstance(item, list):
            return_list = [self._expandWildcardHelper(i) for i in item]
        else:
            return_list = self._expandWildcardHelper(item)
        return [r for r in return_list if r] # filter empty entries

    def _expandWildcardHelper(self, item, wildcard=False, is_multiepoch=False):
        # Expand wildcards for an individual file item.
        if isinstance(item, dict):
            # If it's a dict, pull out the "name" attribute, and check if we want to do wildcarding.
            names = item['name']
            wildcard = item.pop('wildcard', wildcard)
            if 'epoch' in item:
                is_multiepoch = item['epoch']=='multiepoch'
        else:
            names = item
        if not wildcard:
            # Easy: just return what we have in a user-friendly format.
            if is_multiepoch:
                if isinstance(names, list):
                    return names
                else:
                    return [names]
            else:
                return stile_utils.flatten(names)
        else:
            if is_multiepoch:
                # We have to be a bit careful about expanding wildcards in the multiepoch case,
                # since we need to keep sets of files together.
                if not hasattr(names, '__iter__'):
                    return sorted(glob.glob(names))
                elif any([hasattr(n, '__iter__') for n in names]):
                    return [self._expandWildcardHelper(n, wildcard, is_multiepoch) for n in names]
                else:
                    return [sorted(glob.glob(n)) for n in names]
            elif hasattr(names, '__iter__'):
                return stile_utils.flatten([self._expandWildcardHelper(n, wildcard, is_multiepoch)
                                            for n in names])
            else:
                return glob.glob(names)

    def _group(self, list, n):
        """
        For a given list of dicts `list`, build up a list of all the files with the same format but
        different object types.  If the length of the file list for each object type with a given
        format is the same as the file list for the other object types with that format, and the
        `group` keyword is not given or is True, then group those together as files that should be
        analyzed together when we need multiple object types.  Return a list of files with the new
        group kwargs, plus a number "n" of groups which have been made.
        """
        format_dict = stile_utils.EmptyFormatDict(type=dict)
        return_list = []
        for l in list:
            if l:
                if not isinstance(l, dict):
                    raise TypeError('Outputs from _parseFileHelper should always be lists of '+
                                    'dicts.  This is a bug.')
                if not 'group' in l or l['group'] is True:
                    format_obj = stile_utils.Format(epoch=l['epoch'], extent=l['extent'],
                                                    data_format=l['data_format'])
                    if not format_obj.str in format_dict: # In case of user-defined formats
                        format_dict[format_obj.str] = {}
                    if not l['object_type'] in format_dict[format_obj.str]:
                        format_dict[format_obj.str][l['object_type']] = []
                    this_dict = format_dict[format_obj.str][l['object_type']]
                    if isinstance(l['name'], str) or l['epoch']=='multiepoch':
                        return_list.append(l)
                        this_dict.append(len(return_list)-1)
                    else:
                        for lname in l['name']:
                            new_dict = copy.deepcopy(l)
                            new_dict['name'] = lname
                            return_list.append(new_dict)
                            this_dict.append(len(return_list)-1)
                else:
                    return_list.append(l)
        for key in format_dict:
            if format_dict[key]:
                # Check if there are multiple object_types for this format and, if so, if the file
                # lists are the same length
                len_files_list = [len(format_dict[key][object_type])
                                  for object_type in format_dict[key]]
                if len(len_files_list)>1 and len(set(len_files_list))==1:
                    for object_type in format_dict[key]:
                        curr_n = n
                        for i in format_dict[key][object_type]:
                            return_list[i]['group'] = '_stile_group_'+str(curr_n)
                            curr_n+=1
                    if not curr_n-n == len_files_list[0]:
                        raise RuntimeError('Number of found files is greater than number of '+
                                           'expected files: this is a bug')
                    n = curr_n
        return return_list, n

    def _formatFileList(self, list):
        """
        Turn a list of dicts back into a dict whose keys are the string versions of the format_obj
        objects corresponding to the formats in each item of the original list and whose values are
        themselves dicts, with keys being the object types and values being a list of dicts
        containing all the other information about each file.  E.g.,
        {'multiepoch-CCD-catalog': {
            'galaxy': [file1_dict, file2_dict, ...],
            'star': [file3_dict, file4_dict, ...]
            }
        }
        """
        return_dict = {}
        for item in list:
            format_obj = stile_utils.Format(epoch=item.pop('epoch'), extent=item.pop('extent'),
                                            data_format=item.pop('data_format'))
            return_dict[format_obj.str] = return_dict.get(format_obj.str, {})
            object_type = item.pop('object_type')
            return_dict[format_obj.str][object_type] = return_dict[format_obj.str].get(object_type,
                                                                                       [])
            if format_obj.epoch=="multiepoch":
                return_dict[format_obj.str][object_type].append(item)
            else:
                # If there name argument is a list of names, then turn it into one dict per name.
                names = stile_utils.flatten(item.pop('name'))
                for name in names:
                    new_dict = copy.deepcopy(item)
                    if isinstance(name, dict):
                        new_dict.update(name)
                    else:
                        new_dict['name'] = name
                    return_dict[format_obj.str][object_type].append(new_dict)
        return return_dict

    def _fixGroupings(self, list_of_dicts):
        """
        Take a list of dicts as output by self._formatFileList() and merge them into one dict.
        Return that dict and a dict describing the groups (as output by self._getGroups()).
        """
        list_of_dicts = stile_utils.flatten(list_of_dicts)
        if not list_of_dicts:
            return {}, self._getGroups({})
        files = list_of_dicts.pop(0)
        for dict in list_of_dicts:
            for key in dict.keys():
                if key in files:
                    files[key] = self._merge(files[key], dict[key])
                else:
                    files[key] = dict[key]
        for key in files:
            for obj_type in files[key]:
                del_list = []
                for i, item1 in enumerate(files[key][obj_type]):
                    if 'group' in item1 and isinstance(item1['group'], bool):
                        # If "group" is true but no group has been assigned, delete the 'group' key
                        del item1['group']
                    for j, item2 in enumerate(files[key][obj_type][i+1:]):
                        # Now cycle through the file list.  If there are two items which are the
                        # same except for the 'group' key, make the 'group' key of the first item a
                        # list containing all the group IDs from both, then mark the other instance
                        # of the same item for deletion (but don't delete it yet since we're in the
                        # middle of a loop).
                        if 'group' in item2 and isinstance(item2['group'], bool):
                            del item2['group']
                        item_diff_keys = set(item1.keys()).symmetric_difference(set(item2.keys()))
                        if (not (j+i+1 in del_list) and
                            (not item_diff_keys or item_diff_keys==set(['group'])) and
                            all([item1[ikey]==item2[ikey] for ikey in item1.keys()
                                 if ikey!='group'])):
                            item1['group'] = (stile_utils.flatten(item1.get('group', []))+
                                              stile_utils.flatten(item2.get('group', [])))
                            del_list.append(j+i+1)
                # Get rid of duplicate items; go from the back end, so you don't mess up the later
                # indices.
                del_list.sort()
                del_list.reverse()
                for j in del_list:
                    files[key][obj_type].pop(j)
        return files, self._getGroups(files)

    def _merge(self, dict1, dict2):
        """
        Merge two dicts into one, concatenating rather than replacing any keys that are in both
        dicts.
        """
        for key in dict1:
            if key in dict2:
                if isinstance(dict1[key], list):
                    if isinstance(dict2[key], list):
                        dict1[key] += dict2[key]
                    else:
                        dict1[key] += [dict2[key]]
                else:
                    if isinstance(dict2[key], list):
                        dict1[key] = [dict1[key]] + dict2[key]
                    else:
                        dict1[key] = [dict1[key], dict2[key]]
        for key in dict2:
            if key not in dict1:
                dict1[key] = dict2[key]
        return dict1

    def _getGroups(self, file_dict):
        """
        Make a dict corresponding to file_dict (an output of self._fixGroupings() above) with the
        following structure:
        {group_name:
            {format_key:
                {object_type_1: index into the corresponding list in file_dict,
                 object_type_2: index into the corresponding list in file_dict, ...
                }
            }
        }

        """
        if not file_dict:
            return {}
        groups = {}
        # Make a dict with the indices of the files corresponding to each group like:
        # dict[format][object_type] = [(index1, group_name1), ...]
        for key in file_dict.keys():
            groups[key] = {}
            for obj_type in file_dict[key].keys():
                groups[key][obj_type] = [(i, item['group'])
                                         for i, item in enumerate(file_dict[key][obj_type])
                                         if isinstance(item, dict) and 'group' in item]
        reverse_groups = {}
        # Then, back this out to make a list keyed by the group name and indexing all the
        # files in it.
        for key in groups:
            for obj_type in groups[key]:
                for i, group_names in groups[key][obj_type]:
                    if not isinstance(group_names, list):
                        group_names = [group_names]
                    for group_name in group_names:
                        if not isinstance(group_name, bool):
                            if not group_name in reverse_groups:
                                reverse_groups[group_name] = {key: {}}
                            elif not key in reverse_groups[group_name]:
                                raise ValueError('More than one format type found in group '+
                                  '%s: %s, %s'%(group_name, key, reverse_groups[group_name].keys()))
                            if obj_type in reverse_groups[group_name][key]:
                                raise RuntimeError("Multiple files with same object type indicated"+
                                    " for group %s: %s, %s"%(group_name,
                                    reverse_groups[group_name][key][obj_type],
                                    file_dict[key][obj_type][i]))
                            reverse_groups[group_name][key][obj_type] = i
        # Now eliminate any duplicate groups
        del_list = []
        keys = reverse_groups.keys()
        for i, group in enumerate(keys):
            if group not in del_list:
                for j, group2 in enumerate(keys[i+1:]):
                    if group2 not in del_list:
                        if reverse_groups[group]==reverse_groups[group2]:
                            del reverse_groups[group2]
                            del_list.append(group2)
                            self._removeGroup(file_dict, group2)
        return reverse_groups

    def _removeGroup(self, file_dict, group):
        """
        Remove a group name from every file descriptor it's part of.
        """
        for key in file_dict:
            for obj_type in file_dict[key]:
                for file in file_dict[key][obj_type]:
                    if 'group' in file:
                        if isinstance(file['group'], list):
                            if group in file['group']:
                                file['group'].remove(group)
                        else:
                            if file['group']==group:
                                file['group'] = True

    def addKwarg(self, key, value, file_dicts, format_keys=[], object_type_key=None, append=False):
        """
        Add the given (key, value) pair to all the lowest-level dicts in file_list if the key is not
        already present.  To be used for global-level keys AFTER all the individual file descriptors
        have been read in (ie this won't override anything that's already in the file dicts).

        The "value" can be a dict with the desired argument in "name" and specific directions for
        which formats/object types to apply to in the other key/value pairs.  For example, one could
        pass:
            key='file_reader'
            value={'name': 'ASCII', 'extent': 'CCD'}
        and then ONLY the lowest-level dicts whose extent is 'CCD' would be changed (again, only if
        there is no existing 'file_reader' key: this method never overrides already-existing keys).

        @param key              The key to be added
        @param value            The value of that key (plus optional limits, see above)
        @param file_dicts       A list of file_dicts in nested format
        @param format_keys      Only change these format keys! (list of strings, default: [])
        @param object_type_key  Only change this object type key! (string, default: None)
        @returns                The original file_dicts, with added keys as requested.

        Note that the end user generally shouldn't pass format_keys or object_type_key arguments:
        those kwargs are intended for use by this function itself in recursive calls.
        """
        # Note to coders: this is very similar to addItem below and any bugs found here might also
        # appear there.
        # If there are no remaining restrictions to process:
        if not isinstance(value, dict) or value.keys()==['name']:
            if isinstance(value, dict):
                value = value.pop('name')
            for file_dict in file_dicts:
                for format in file_dict:
                    for object_type in file_dict[format]:
                        for file in file_dict[format][object_type]:
                            if not key in file or not file[key] or append:
                                # If no restrictions are present, or if this file meets the
                                # restrictions:
                                if ((not format_keys or (format_keys and
                                     all([format_key in format for format_key in format_keys]))) and
                                    (not object_type_key or object_type==object_type_key)):
                                    if append:
                                        if not hasattr(file[key],'append'):
                                            file[key] = [file[key]]
                                        file[key].append(value)
                                    else:
                                        file[key] = value
        else:
            # In this case, strip out all the remaining dict keys in sequence and recurse.
            object_types = [object_type for file_dict in file_dicts for format in file_dict
                            for object_type in file_dict[format]]
            value_keys = value.keys()
            # If this does not look like it has any remaining format or object keys, then it's
            # probably a dict that's supposed to be the value of a key.  Call this function
            # again, but with {'name': value} instead, so it gets caught by the previous branch of
            # this if statement.
            if not any([v==obj for v in value_keys for obj in object_types] +
                       [v in format.split('-') for v in value_keys for file_dict in file_dicts
                        for format in file_dict]) and key=='fields':
                self.addKwarg(key, {'name': value}, file_dicts, format_keys,
                              object_type_key, append)
            # Otherwise, recursively call this function with the extra formats/object types included
            else:
                for value_key in value_keys:
                    if value_key in value: # in case it was popped in a call earlier in this loop
                        new_value = value.pop(value_key)
                        if value_key=='extent' or value_key=='data_format' or value_key=='epoch':
                            self.addKwarg(key, value, file_dicts,
                                          format_keys=stile_utils.flatten([format_keys, new_value]),
                                          object_type_key=object_type_key)
                        elif value_key=='object_type':
                            self.addKwarg(key, value, file_dicts, format_keys=format_keys,
                                          object_type_key=new_value)
                        elif value_key in object_types:
                            self.addKwarg(key, new_value, file_dicts, format_keys=format_keys,
                                          object_type_key=value_key)
                        elif value_key=='name':
                            self.addKwarg(key, new_value, file_dicts, format_keys=format_keys,
                                          object_type_key=object_type_key)
                        else:
                            new_format_keys = stile_utils.flatten([format_keys, value_key])
                            self.addKwarg(key, new_value, file_dicts, format_keys=new_format_keys,
                                          object_type_key=object_type_key)
        return file_dicts

    def addItem(self, item, sys_test_dict, format_keys=[]):
        """
        Add the given item pair to all the lists of sys_tests in sys_test_dict.

        The "item" can be a dict with specific directions for which formats to sys_test in the
        key/value pairs.  For example, one could pass:
            item={'name': 'CorrelationFunction', 'type': 'GalaxyShear', 'extent': 'CCD'}
        and then ONLY the lists of sys_tests whose extent is 'CCD' would be changed.

        @param item             The item to be added
        @param sys_test_dict    A dict of sys_tests to be done (as {format: list_of_sys_tests})
        @param format_keys      Only change these format keys! (list of strings, default: [])
        @returns                The original sys_test_dict, with added sys_tests as requested.

        Note that the end user generally shouldn't pass the format_keys argument: that kwarg is
        intended for use by this function itself in recursive calls.
        """
        # Note to coders: this is very similar to addKwarg above and any bugs found here might also
        # appear there.
        # (this one is much simpler since A) we don't require all formats and B) there's a clear
        # separation between what you're adding, and what's describing where you add it, since one
        # is a dict and the other is a list or list item)
        # If there are no remaining restrictions to process:
        item_keys = item.keys()
        if not ('extent' in item_keys or 'epoch' in item_keys or 'data_format' in item_keys):
            for format in sys_test_dict:
                # If no restrictions are present, or if this file meets the restrictions:
                if (not format_keys or (format_keys and
                    all([format_key in format for format_key in format_keys]))):
                    sys_test_dict[format].append(item)
        else:
            for item_key in item_keys:
                # in case it was popped in a call earlier in this loop, or in a recursive call:
                if item_key in item:
                    if item_key=='extent' or item_key=='data_format' or item_key=='epoch':
                        new_value = item.pop(item_key)
                        self.addItem(item, sys_test_dict,
                                     format_keys=stile_utils.flatten([format_keys, new_value]))
        return sys_test_dict

    def _checkAndCoerceFormat(self, epoch, extent, data_format):
        """
        Check for proper formatting of the epoch/extent/data_format kwargs and turn them into a
        string so we can use them as dict keys.
        """
        if not isinstance(epoch, stile_utils.Format) and (not hasattr(epoch, '__str__') or
            (extent and not hasattr(extent, '__str__')) or
            (data_format and not hasattr(data_format, '__str__'))):
            raise ValueError('epoch (and extent and data_format) must be printable as strings; '+
                             'given %s %s %s'%(epoch, extent, data_format))
        if extent or data_format:
            epoch = stile_utils.Format(epoch=epoch, extent=extent, data_format=data_format).str
        if isinstance(epoch, stile_utils.Format):
            epoch = epoch.str
        return epoch

    def makeTest(self, sys_test):
        """
        Given a definition of a SysTest contained in a dictionary (with the type of SysTest
        defined by the "name" (general class) and "type" (specific test)), return a dictionary
        containing the necessary information to run the test.

        @param sys_test  A dictionary defining a SysTest
        @returns         A dictionary with the following entries:
                            - 'sys_test': a stile.SysTest object
                            - 'bin_list': a list of stile.BinStep or stile.BinList objects to
                              be applied to the data
                            - 'extra_args': a dict of extra keyword arguments to be passed to
                              calls of the returned 'sys_test'.
        """
        # Check inputs for proper formats and keys
        if not isinstance(sys_test, dict):
            raise ValueError('Sys test descriptions (from ConfigDataHandler) must be dicts--this '+
                             'is a bug')
        if 'name' not in sys_test:
            raise ValueError('Sys tests are defined by a "name" argument - not found')
        if sys_test['name'] not in self.expected_systest_keys:
            raise ValueError('Do not understand sys test name %s'%sys_test['name'])
        unexpected_keys = [key for key in sys_test
                           if key not in self.expected_systest_keys[sys_test['name']]]
        if unexpected_keys:
            raise ValueError('Got unexpected key or keys %s for sys test type %s'%(unexpected_keys,
                                                                                  sys_test['name']))

        # Process the non-sys-test args
        if 'extra_args' in sys_test:
            extra_args = sys_test['extra_args']
        else:
            extra_args = {}
        if 'bins' in sys_test:
            bin_list = self.makeBins(sys_test['bins'])
        else:
            bin_list = []

        # Turn the dicts into actual SysTest objects
        if sys_test['name'] == 'CorrelationFunction':
            if 'type' not in sys_test:
                raise ValueError('Must pass "type" argument for CorrelationFunction systematics '+
                                 'tests')
            # Next line for when PR #56 is merged
            # return_test = sys_tests.CorrelationFunctionSysTest(sys_test['type'])
            return_test = eval('sys_tests.'+sys_test['type']+'SysTest()')
            if 'treecorr_kwargs' in sys_test:
                extra_args.update(sys_test['treecorr_kwargs'])
        elif sys_test['name'] == 'ScatterPlot':
            if 'type' not in sys_test:
                raise ValueError('Must pass "type" argument for ScatterPlot systematics '+
                                 'tests')
            # Next line for when PR #56 is merged
            # return_test = sys_tests.ScatterPlotSysTest(sys_test['type'])
            return_test = eval('sys_tests.ScatterPlot'+sys_test['type']+'SysTest()')
        elif sys_test['name'] == 'WhiskerPlot':
            if 'type' not in sys_test:
                raise ValueError('Must pass "type" argument for WhiskerPlot systematics '+
                                 'tests')
            # Next line for when PR #56 is merged
            # return_test = sys_tests.WhiskerPlotSysTest(sys_test['type'])
            return_test = eval('sys_tests.WhiskerPlot'+sys_test['type']+'SysTest()')
        elif sys_test['name'] == 'Stat':
            if 'field' not in sys_test:
                raise ValueError('Must pass "field" argument for Stat sys test')
            if 'object_type' not in sys_test:
                raise ValueError('Must pass "object_type" argument for Stat sys test')
            return_test = sys_tests.StatSysTest(field=sys_test['field'])
            return_test.objects_list = [sys_test['object_type']]  # for automated processing
        return {'sys_test': return_test, 'bin_list': bin_list, 'extra_args': extra_args}

    def makeBins(self, bins):
        """
        Given a definition of a binning scheme contained in a dictionary or list of dictionaries
        (with the type of binning defined by the "name" key, or general binning class), return
        a list of stile.BinList or stile.BinStep objects.

        @param bins  A binning scheme defined by a dict, or a list of them
        @returns     A list of corresponding BinList or BinStep objects
        """
        if isinstance(bins, dict):
            # In case there's just one bin definition as a dict, rather than a list of them
            bins = [bins]
        bin_list = []
        for bin_def in bins:
            # Check for proper formatting
            if not 'name' in bin_def:
                raise ValueError('Bins are defined by a "name" argument - not found')
            if bin_def['name'] not in self.expected_bin_keys:
                raise ValueError('Do not understand bin type name %s'%bin_def['name'])
            if not 'field' in bin_def:
                raise ValueError('Must define a field for the bin to operate on; given '+
                                 'definition %s'%str(bin_def))
            unexpected_keys = [key for key in bin_def
                               if key not in self.expected_bin_keys[bin_def['name']]]
            if unexpected_keys:
                raise ValueError('Got unexpected key or keys %s for bin type %s'%(unexpected_keys,
                                                                                  bin_def['name']))

            # Turn the dict into a Bin* object
            if bin_def['name']=='List':
                if not 'endpoints' in bin_def:
                    raise ValueError('Must define endpoints for BinList-type binning scheme')
                bin_list.append(BinList(bin_def['field'], bin_def['endpoints']))
            elif bin_def['name']=='Step':
                bin_list.append(BinStep(bin_def['field'], low=bin_def.get('low',None),
                                high=bin_def.get('high',None), step = bin_def.get('step', None),
                                n_bins = bin_def.get('n_bins', None),
                                use_log = bin_def.get('use_log', False)))
        return bin_list

    def _expandBins(self, item_list):
        """
        Take a list of files including binning, and turn them into a list of separate "files"
        with one (list of) SingleBin(s) to be applied to each.
        """
        if isinstance(item_list, dict):
            item_list = [item_list]
        return_list = []
        for item in item_list:
            if isinstance(item, list):
                # Recurse
                new_list = []
                for subitem in item:
                    if hasattr(subitem, '__iter__'):
                        new_list.append(self._expandBins(subitem))
                    else:
                        new_list.append(self._expandBins(subitem))
                new_items = [[]]
                # Do the ExpandBinList thing where we make a matrix of lists
                while new_list:
                    this_list = new_list.pop()
                    new_items = [[file]+n_i for file in this_list for n_i in new_items]
                return_list.extend(new_items)
            elif not 'bins' in item:
                return_list.append(item)
            else:
                # This is a single item with a Bin, so copy it N times and put the
                # appropriate (list of) SingleBin(s) in each one.
                if not 'bin_list' in item:
                    bins = ExpandBinList(self.makeBins(item['bins']))
                    new_items = [item.copy() for i in range(len(bins))]
                    for new_item, bin_list in zip(new_items, bins):
                        new_item['bin_list'] = bin_list
                    return_list.extend(new_items)
                else:
                    return_list.append(item)
        return return_list

    def queryFile(self, file_name):
        """
        Return a description of every place the named file occurs in the dict of file descriptors.
        Useful to figure out where a file is going if you're having trouble telling how the
        parser is understanding your config file.
        """
        return_list = []
        for format in self.files:
            for object_type in self.files[format]:
                for item in self.files[format][object_type]:
                    if item['name']==file_name:
                        return_list_item = []
                        return_list_item.append("format: "+format)
                        return_list_item.append("object type: "+object_type)
                        for key in item:
                            if not key=='name':
                                return_list_item.append(key+': '+str(item[key]))
                        return_list.append(str(len(return_list)+1)+' - '+
                                           ', '.join(return_list_item))
        return '\n'.join(return_list)

    def listFileTypes(self):
        """
        Return a list of format strings describing the epoch, extent, and data format of available
        files.
        """
        return [format for format in self.files]

    def listObjects(self, epoch, extent=None, data_format=None):
        """
        Return a list of object types available for the given format.  The format can be given as a
        string "{epoch}-{extent}-{data format}" or as three arguments, epoch, extent, data_format.
        """
        epoch = self._checkAndCoerceFormat(epoch, extent, data_format)
        if epoch in self.files:
            return [obj for obj in self.files[epoch]]
        else:
            return []

    def listData(self, object_type, epoch, extent=None, data_format=None):
        """
        Return a list of data files for the given object_type (or object_types, see below) and data
        format.

        The object_type argument can be a single type, in which case all data files meeting the
        format and object_type criteria are returned in a list.  The object_type argument can also
        be a list/tuple of object types; in that case, if there are pairs (triplets, etc) of files
        which should be analyzed together given those types, the returned value will be a list of
        lists, where the innermost list is a set of files to be analyzed together (with the order of
        the list corresponding to the order of items in the object_type) and the overall list is the
        set of such sets of files.

        Note that "multiepoch" formats will include a LIST of files instead of a single file in all
        cases where a single file is described above (so e.g. a list of object types will retrieve a
        list of lists of lists instead of just a list of lists).

        The format can be given as a string "{epoch}-{extent}-{data format}" or as three arguments,
        epoch, extent, data_format.
        """
        epoch = self._checkAndCoerceFormat(epoch, extent, data_format)
        multiepoch = epoch.split('-')[0]=='multiepoch'
        if (not hasattr(object_type, '__hash__') or (hasattr(object_type, '__iter__') and
            not all([hasattr(obj, '__hash__') for obj in object_type]))):
            raise ValueError('object_type argument must be able to be used as a dictionary key, or'+
                             'be an iterable all of whose elements can be used as dictionary keys:'+
                             ' given %s'%object_type)
        if not hasattr(object_type, '__iter__'):
            if epoch in self.files and object_type in self.files[epoch]:
                return_list = [file for file in self.files[epoch][object_type]]
            else:
                return []
        else:
            groups_list = []
            for group in sorted(self.groups.keys()):  # Sort for unit testing purposes, mainly
                if epoch in self.groups[group] and all([obj in self.groups[group][epoch]
                                                        for obj in object_type]):
                    groups_list.append(group)
            # The "groups" are indices into the self.files list, so do this funny nested dict thing
            # to get the real files and not their indices
            return_list = [[self.files[epoch][obj][self.groups[group][epoch][obj]]
                            for obj in object_type] for group in groups_list]
        return self._expandBins(return_list)

    def getMask(self, data, flag):
        if hasattr(flag, '__iter__'):
            return numpy.logical_and.reduce([self.getMask(data,f) for f in flag], axis=1)
        elif isinstance(flag, str):
            return data[flag]==False
        elif isinstance(flag, dict):
            return numpy.logical_and.reduce([data[key]==flag[key] for key in flag], axis=1)
        else:
            raise ValueError('flag_field kwarg must be a string, list, or dict; given %s'%flag)

    def getData(self, data_id, object_type, epoch, extent=None, data_format=None, bin_list=[]):
        """
        Return the data corresponding to 'data_id' for the given object_type and data format.

        The format can be given as a string "{epoch}-{extent}-{data format}" or as three arguments,
        epoch, extent, data_format.  For the ConfigDataHandler, the 'object_type', 'epoch' and
        'extent' arguments are ignored; only the 'data_format' and 'data_id' kwargs (or the data
        format pulled from a format string) are considered.  The other arguments are kept for
        compatibility of call signatures.

        A list of Bin objects can be passed with the kwarg 'bin_list'.  These bins are "and"ed, not
        looped through!  This is not generally recommended for this ConfigDataHandler since data is
        not cached--it's better to bin the data at another stage, keeping the whole array in memory
        between binnings.  (Some of this caching is done by Python or your OS, but if you have many
        files it may not work.)
        """
        epoch = self._checkAndCoerceFormat(epoch, extent, data_format)
        if not data_format:
            data_format = epoch.split('-')[-1]
        data_format=data_format.lower()
        if not hasattr(object_type, '__hash__') or (hasattr(object_type, '__iter__') and
            not all([hasattr(obj, '__hash__') for obj in object_type])):
            raise ValueError('object_type argument must be able to be used as a dictionary key, or'+
                             ' be an iterable all of whose elements can be used as dictionary '+
                             'keys: given %s'%object_type)

        if isinstance(data_id, str):
            data_id = {'name': data_id}
        if 'fields' in data_id:
            fields = data_id['fields']
        else:
            fields=None

        # For multiepoch data sets with lists in the "name" key
        if hasattr(data_id['name'], '__iter__'):
            if 'multiepoch' not in epoch:
                raise RuntimeError('List of data files can only be given for multiepoch data sets')
            name_list = data_id['name']
            data_list = []
            for name in name_list:
                data_id['name'] = name
                data_list.append(self.getData(data_id, object_type, epoch, bin_list=bin_list))
            data_id['name'] = name_list
            return data_list

        if 'file_reader' in data_id:
            if d['file_reader']=='ASCII':
                data = ReadASCIITable(data_id['name'], fields=fields)
            elif d['file_reader']=='FITS':
                if data_format=='catalog':
                    data = ReadFITSTable(data_id['name'], fields=fields)
                elif data_format=='image':
                    data = ReadFITSImage(data_id['name'])
                else:
                    raise RuntimeError('Data format must be either "catalog" or "image", given '+
                                       '%s'%data_format)
            elif isinstance(d['file_reader'], dict):
                if ('extra_kwargs' in d['file_reader'] and
                    not isinstance(d['file_reader']['extra_kwargs'], dict)):
                    raise ValueError("extra_kwargs argument of file_reader option must be a dict, "+
                                     "given "+str(d['file_reader']['extra_kwargs']))
                if 'name' not in d['file_reader']:
                    if 'image' in epoch:
                        data = ReadImage(data_id['name'],
                                         **d['file_reader'].get('extra_kwargs', {}))
                    else:
                        data = ReadTable(data_id['name'], fields=fields,
                                         **d['file_reader'].get('extra_kwargs', {}))
                elif d['file_reader']['name']=='ASCII':
                    data = ReadASCIITable(data_id['name'], fields=fields,
                                          **d['file_reader'].get('extra_kwargs', {}))
                elif d['file_reader']['name']=='FITS':
                    data = ReadFITSTable(data_id['name'], fields=fields,
                                         **d['file_reader'].get('extra_kwargs', {}))
                else:
                    raise ValueError('Do not understand file_reader type: '+
                                     str(d['file_reader']['name']))
            else:
                raise ValueError('Do not understand file_reader type: %s'%str(d['file_reader']))
        elif 'catalog' in epoch:
            data = ReadTable(data_id['name'], fields=fields)
        elif 'image' in epoch:
            data = ReadImage(data_id['name'])
        else:
            raise RuntimeError('Data format must be either "catalog" or "image", given '+
                               '%s'%data_format)
        if 'flag_field' in data_id and data_id['flag_field']:
            data = data[self.getMask(data, data_id['flag_field'])]
        bins_to_do = bin_list + data_id.get('bin_list', [])
        if bins_to_do:
            for bin in bins_to_do:
                data = bin(data)
            if 'nickname' in data_id:
                data_id['nickname'] = '_'.join([data_id['nickname']]+
                                               [b.short_name for b in bins_to_do])
        return data

