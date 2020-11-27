"""
Agentpy Output Module
Content: DataDict class for output data
"""

import pandas as pd

from os import listdir, makedirs
import json

from .tools import AttrDict, make_list, AgentpyError

import numpy as np


class NpEncoder(json.JSONEncoder):
    """ Adds support for numpy number formats to json """
    # By Jie Yang https://stackoverflow.com/a/57915246

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return super(NpEncoder, self).default(obj)


def _last_exp_id(name, path):
    """ Identifies existing experiment data and return highest id. """

    exp_id = 0
    output_dirs = listdir(path)
    exp_dirs = [s for s in output_dirs if name in s]
    if exp_dirs:
        ids = [int(s.split('_')[-1]) for s in exp_dirs]
        exp_id = max(ids)
    return exp_id


class DataDict(AttrDict):
    """ Dictionary for recorded simulation data.

    Generated by :class:`model`, :class:`experiment`, or :func:`load`.
    Dictionary items can be defined and accessed like attributes.
    Attributes can differ from the standard ones listed below.

    Attributes:
        log (dict): Meta-data of the simulation
            (e.g. name, time-stamps, settings, etc.)
        parameters (dict, pandas.DataFrame, or DataDict):
            Parameters that have been used for the simulation.
        variables (pandas.DataFrame or DataDict)):
            Dynamic variables, seperated per object type,
            which can be recorded once per time-step with :func:`record`.
        measures (pandas.DataFrame): Evaluation measures,
            which can be recorded once per run with :func:`measure`.
    """

    def __repr__(self, indent=False):

        rep = ""
        if not indent:
            rep += "DataDict {"
        i = '    ' if indent else ''

        for k, v in self.items():
            rep += f"\n{i}'{k}': "
            if isinstance(v, pd.DataFrame):
                lv = len(list(v.columns))
                rv = len(list(v.index))
                rep += f"DataFrame with {lv} " \
                       f"variable{'s' if lv != 1 else ''} " \
                       f"and {rv} row{'s' if rv != 1 else ''}"
            elif isinstance(v, DataDict):
                rep += f"{v.__repr__(indent=True)}"
            elif isinstance(v, dict):
                lv = len(list(v.keys()))
                rep += f"Dictionary with {lv} key{'s' if lv != 1 else ''}"
            elif isinstance(v, list):
                lv = len(v)
                rep += f"List with {lv} entr{'ies' if lv != 1 else 'y'}"
            else:
                rep += f"Object of type {type(v)}"

        if not indent:
            rep += "\n}"

        return rep

    def _combine_vars(self, obj_types=None, var_keys=None):

        """ Returns pandas dataframe with variables """

        # Select dataframes
        df_dict = self['variables']

        # If 'variables' is a dataframe
        if isinstance(df_dict, pd.DataFrame):
            return df_dict

        # If 'variables' is a DataDict with only one entry
        if isinstance(df_dict, DataDict) and len(df_dict.keys()) == 1:
            return list(df_dict.values())[0]

        # If 'variables' is a dictionary
        # TODO introduce checks & errors

        # Select object types
        if var_keys is not None:
            df_dict = {k: v for k, v in df_dict.items()
                       if any(x in v.columns for x in make_list(var_keys))}
        if obj_types is not None:
            df_dict = {k: v for k, v in df_dict.items() if k in obj_types}

        # Create dataframe
        df = pd.concat(df_dict)
        df.index = df.index.set_names('obj_type', level=0)  # Name new index
        if var_keys:
            df = df[var_keys]  # Select var_keys

        return df

    def _combine_pars(self):

        """ Returns pandas dataframe with parameters and run_id """

        # Combine fixed & varied parameters
        if isinstance(self.parameters, DataDict):
            dfp0 = self.parameters.varied
            for k, v in self.parameters.fixed.items():
                dfp0[k] = v

        # Take either fixed or varied parameters
        elif isinstance(self.parameters, dict):
            dfp0 = pd.DataFrame({k: [v] for k, v in self.parameters.items()})
        elif isinstance(self.parameters, pd.DataFrame):
            dfp0 = self.parameters
        else:
            raise AgentpyError("Parameters must be of type "
                               "dict, DataDict, or pandas.DataFrame")

        # Multiply for iterations
        dfp = pd.concat([dfp0] * self.log['iterations'])
        dfp = dfp.reset_index(drop=True)
        dfp.index.name = 'run_id'

        return dfp

    def arrange(self, data_keys=None, var_keys=None, obj_types=None,
                measure_keys=None, param_keys=None, scenarios=None,
                index=False):
        """ Combines and/or filters data based on passed arguments.

        Arguments:
            data_keys (str or list of str, optional):
                Keys from the DataDict to include in the new dataframe.
                If none are given, all are selected.
            obj_types (str or list of str, optional):
                Agent and/or environment types to include in the new dataframe.
                Only takes effect if data_keys include 'variables'.
                If none are given, all are selected.
            var_keys (str or list of str, optional):
                Dynamic variables to include in the new dataframe.
                Only takes effect if data_keys include 'variables'.
                If none are given, all are selected.
            param_keys (str or list of str, optional):
                Parameters to include in the new dataframe.
                Only takes effect if data_keys include 'parameters'.
                If none are given, all are selected.
            measure_keys (str or list of str, optional):
                Measures to include in the new dataframe.
                Only takes effect if data_keys include 'measures'.
                If none are given, all are selected.
            scenarios (str or list of str, optional):
                Scenarios to include in the new dataframe.
                If none are given, all are selected.
            index (bool, optional):
                Whether to keep original multi-index structure (default False).

        Returns:
            pandas.DataFrame: The arranged dataframe
        """

        dfv = None  # The dataframe to be arranged
        supported_keys = ['variables', 'measures', 'parameters']

        # Prepare keys (select all if none are given)
        if data_keys is None:
            data_keys = [k for k in self.keys()
                         if k in supported_keys]
        else:
            data_keys = make_list(data_keys)
            for key in data_keys:
                if key not in self.keys():
                    raise KeyError(f"DataDict has no key '{key}'")
                elif key not in supported_keys:
                    raise KeyError(f"DataDict.arrange doesn't support '{key}'"
                                   f"Supported keys are: {supported_keys}")

        # Process 'variables'
        if 'variables' in data_keys:
            dfv = self._combine_vars(obj_types, var_keys)

        # Process 'measures'
        if 'measures' in data_keys:
            dfm = self.measures
            if measure_keys:
                dfm = dfm[measure_keys]
            if dfv is None:
                dfv = dfm
            else:
                # Combine vars & measures
                index_keys = dfv.index.names
                dfm = dfm.reset_index()
                dfv = dfv.reset_index()
                dfv = pd.concat([dfm, dfv])
                dfv = dfv.set_index(index_keys)

        # Process 'parameters'
        if 'parameters' in data_keys:
            dfp = self._combine_pars()
            if param_keys:
                dfp = dfp[param_keys]
            if isinstance(dfv.index, pd.MultiIndex):
                dfp = dfp.reindex(dfv.index, level='run_id')
            dfv = pd.concat([dfv, dfp], axis=1)

        # Select scenarios
        if scenarios:
            scenarios = make_list(scenarios)  # noqa
            dfv = dfv.query("scenario in @scenarios")

        # Reset index
        if not index:
            dfv = dfv.reset_index()

        return dfv

    def save(self, exp_name=None, exp_id=None, path='ap_output', display=True):

        """ Writes output data to directory ``{path}/{exp_name}_{exp_id}/``.

        Arguments:
            exp_name (str, optional): Name of the experiment.
                If none is passed, the name of the experiment instance is used.
            exp_id (int, optional): Number of the experiment.
                If none is passed, a new id is generated.
            path (str, optional): Target directory (default 'ap_output').
            display (bool, optional): Display saving progress (default True).

        """

        # Create output directory if it doesn't exist
        if path not in listdir():
            makedirs(path)

        # Set exp_name
        if exp_name is None:
            exp_name = self.log['name']
        exp_name = exp_name.replace(" ", "_")

        # Set exp_id
        if exp_id is None:
            exp_id = _last_exp_id(exp_name, path) + 1

        # Create new directory for output
        path = f'{path}/{exp_name}_{exp_id}'
        makedirs(path)

        # Save experiment data
        for key, output in self.items():

            if isinstance(output, pd.DataFrame):
                output.to_csv(f'{path}/{key}.csv')

            if isinstance(output, DataDict):
                for k, o in output.items():

                    if isinstance(o, pd.DataFrame):
                        o.to_csv(f'{path}/{key}_{k}.csv')
                    elif isinstance(o, dict):
                        with open(f'{path}/{key}_{k}.json', 'w') as fp:
                            json.dump(o, fp, cls=NpEncoder)

            elif isinstance(output, dict):
                with open(f'{path}/{key}.json', 'w') as fp:
                    json.dump(output, fp, cls=NpEncoder)

            # elif t == nx.Graph:
            #    nx.write_graphml(output, f'{path}/{key}.graphml')

        if display:
            print(f"Data saved to {path}")

    def _load(self, exp_name=None, exp_id=None,
             path='ap_output', display=True):
        # TODO If none is passed, first experiment name in directory is used.

        def load_file(path, file, display):

            if display:
                print(f'Loading {file} - ', end='')

            i_cols = ['sample_id', 'run_id', 'scenario',
                      'env_key', 'agent_id', 'obj_id', 't']

            ext = file.split(".")[-1]
            # key = file[:-(len(ext) + 1)]

            path = path + file

            try:
                if ext == 'csv':
                    obj = pd.read_csv(path)
                    index = [i for i in i_cols if i in obj.columns]
                    if index:
                        obj = obj.set_index(index)
                elif ext == 'json':
                    with open(path, 'r') as fp:
                        obj = json.load(fp)
                # elif ext == 'graphml': TODO Add support for graphs
                #    self[key] = nx.read_graphml(path)
                else:
                    if display:
                        print(f"Error: File type '{ext}' not supported")
                    return None

                if display:
                    print('Successful')

                return obj

            except Exception as e:
                print(f'Error: {e}')

        # Prepare for loading
        # TODO if exp_name is None:
        exp_name = exp_name.replace(" ", "_")
        if not exp_id:
            exp_id = _last_exp_id(exp_name, path)
            if exp_id == 0:
                raise AgentpyError(f"No experiment found with "
                                   f"name '{exp_name}' in path '{path}'")
        path = f'{path}/{exp_name}_{exp_id}/'
        if display:
            print(f'Loading from directory {path}')

        # Loading data
        for file in listdir(path):
            if 'variables_' in file:
                if 'variables' not in self:
                    self['variables'] = DataDict()
                ext = file.split(".")[-1]
                key = file[:-(len(ext) + 1)].replace('variables_', '')
                self['variables'][key] = load_file(path, file, display)
            elif 'parameters_' in file:
                ext = file.split(".")[-1]
                key = file[:-(len(ext) + 1)].replace('parameters_', '')
                if 'parameters' not in self:
                    self['parameters'] = DataDict()
                self['parameters'][key] = load_file(path, file, display)
            else:
                ext = file.split(".")[-1]
                key = file[:-(len(ext) + 1)]
                self[key] = load_file(path, file, display)
        return self


def load(exp_name=None, exp_id=None, path='ap_output', display=True):
    """ Reads output data from directory ``{path}/{exp_name}_{exp_id}/``.

        Arguments:
            exp_name (str): Experiment name.
            exp_id (int, optional): Number of the experiment.
                If none is passed, the highest id in target directory is used.
            path (str, optional): Target directory (default 'ap_output').
            display (bool, optional): Display loading progress (default True).

        Returns:
            DataDict: The loaded data.
    """
    return DataDict()._load(exp_name, exp_id, path, display)
