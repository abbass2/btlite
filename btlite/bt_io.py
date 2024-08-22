# $$_ Lines starting with # $$_* autogenerated by jup_mini. Do not modify these
# $$_code
# $$_ %%checkall
from __future__ import annotations
import h5py
import string
import os
import numpy as np
import pandas as pd
import datetime
from typing import Any
import tempfile
from btlite.bt_utils import get_child_logger, assert_

_logger = get_child_logger(__name__)


def np_arrays_to_hdf5(data: dict[str, np.ndarray], 
                      filename: str, 
                      key: str, 
                      dtypes: dict[str, str] | None = None, 
                      as_utf8: list[str] | None = None,
                      compression_args: dict[Any, Any] | None = None) -> None:
    '''
    Write a list of numpy arrays to hdf5
    Args:
        data: list of numpy one dimensional arrays along with the name of the array
        filename: filename of the hdf5 file
        key: group and or / subgroups to write to.  For example, "g1/g2" will write to the subgrp g2 within the grp g1
        dtypes: dict used to override datatype for a column.  For example, {"col1": "f4"} will write a 4 byte float array for col1
        as_utf_8: each column listed here will be saved with utf8 encoding. For all other strings, we will compute the max length
        and store as a fixed length byte array with ascii encoding, i.e. a S[max length] datatype. This is much faster to read and process
        compression_args: if you want to compress the hdf5 file. You can use the hdf5plugin module and arguments such as hdf5plugin.Blosc()
    '''
    if not len(data): return
    tmp_key = key + '_tmp'
    
    if compression_args is None:
        compression_args = {}
        
    if as_utf8 is None:
        as_utf8 = []
    
    with h5py.File(filename, 'a') as f:
        if tmp_key in f: del f[tmp_key]
        grp = f.create_group(tmp_key)
        for colname, array in data.items():
            if dtypes is not None and colname in dtypes:
                dtype = np.dtype(dtypes[colname])
                if dtype.kind == 'M':  # datetime
                    dtype = h5py.opaque_dtype(dtype)
                    array = array.astype(dtype)
                else:
                    array = array.astype(dtype)
            else:  # we need to figure out datatype
                dtype = array.dtype
                if colname in as_utf8:
                    array = np.char.encode(array.astype('U'), 'utf-8')
                elif dtype.kind == 'O':
                    array = np.where(array == None, '', array)  # noqa: E711 comparison to None should be 'if cond is None:'
                    array = array.astype('S')
                elif dtype.kind == 'M':  # datetime
                    dtype = h5py.opaque_dtype(dtype)
                    array = array.astype(dtype)
            if colname in grp:
                del grp[colname]
            grp.create_dataset(name=colname, data=array, shape=[len(array)], dtype=array.dtype, **compression_args)
            
        grp.attrs['type'] = 'dataframe'
        grp.attrs['timestamp'] = str(datetime.datetime.now())
        grp.attrs['rows'] = len(array)
        grp.attrs['columns'] = ','.join([colname for colname in data.keys()])
        grp.attrs['utf8_cols'] = ','.join(as_utf8)

        if key in f: 
            del f[key]
        f.move(tmp_key, key)
        f.flush()
        

def hdf5_to_np_arrays(filename: str, key: str) -> dict[str, np.ndarray]:
    '''
    Read a list of numpy arrays previously written out by np_arrays_to_hdf5
    Args:
        filename: path of the hdf5 file to read
        key: group and or / subgroups to read from.  For example, "g1/g2" will read from the subgrp g2 within the grp g1
    Return:
        a list of numpy arrays along with their names
        '''
    ret: dict[str, np.ndarray] = {}
    with h5py.File(filename, 'r') as f:
        if key not in f:
            _logger.info(f'{key} not found in {filename}')
            return dict()
        grp = f[key]
        assert_('type' in grp.attrs and grp.attrs['type'] == 'dataframe', f'{key} not a dataframe')
        columns = grp.attrs['columns'].split(',')
        utf8_cols: list[str] = []
        if 'utf8_cols' in grp.attrs:
            utf8_cols = grp.attrs['utf8_cols'].split(',')
        for col in columns:
            array = grp[col][:]
            if col in utf8_cols:
                array = np.char.decode(array, 'utf-8')
                dtype = f'U{array.dtype.itemsize}'
            if array.dtype.kind == 'S':
                # decode bytes to numpy unicode
                dtype = f'U{array.dtype.itemsize}'
                array = array.astype(dtype)
            elif array.dtype == 'O':
                array = array.astype('S')
                array = np.char.decode(array, encoding='utf-8')
            ret[col] = array
    return ret
        
        
def df_to_hdf5(df: pd.DataFrame, 
               filename: str, 
               key: str, 
               dtypes: dict[str, str] | None = None,
               as_utf8: list[str] | None = None) -> None:
    '''
    Write out a pandas dataframe to hdf5 using the np_arrays_to_hdf5 function
    '''
    arrays: dict[str, np.ndarray] = {}
    for column in df.columns:
        arrays[column] = df[column].values
    np_arrays_to_hdf5(arrays, filename, key, dtypes, as_utf8)
    

def hdf5_to_df(filename: str, key: str) -> pd.DataFrame:
    '''
    Read a pandas dataframe previously written out using df_to_hdf5 or np_arrays_to_hdf5
    '''
    arrays = hdf5_to_np_arrays(filename, key)
    if not len(arrays): return pd.DataFrame()
    array_dict = {name: array for name, array in arrays.items()}
    return pd.DataFrame(array_dict)


def hdf5_repack(in_filename: str, out_filename: str) -> None:
    '''
    Copy groups from input filename to output filename.
    Serves the same purpose as the h5repack command line tool, i.e. 
    discards empty space in the input file so the output file may be smaller
    '''
    with h5py.File(in_filename, 'r') as inf:
        num_items = len(list(inf.keys()))
        with h5py.File(out_filename + '.tmp', 'w') as outf:
            for i, name in enumerate(inf):
                _logger.info(f'copying {name} {i} of {num_items}')
                # recursively copies subgroups and datasets
                inf.copy(inf[name], outf)
    os.rename(out_filename + '.tmp', out_filename)
    

def hdf5_copy(in_filename: str, in_key: str, out_filename: str, out_key: str | None = None, skip_if_exists: bool = True) -> None:
    '''
    Recursively copy groups from input filename to output filename.
    Args:
        skip_if_exists: if set, we will skip any groups in the output that already exist.
        Otherwise we replace them.
    >>> tempdir = get_temp_dir()
    >>> in_filename = tempdir + '/temp_in.hdf5'
    >>> out_filename = tempdir + '/temp_out.hdf5'
    >>> for filename in [in_filename, out_filename]:
    ...    if os.path.exists(filename): os.remove(filename)
    >>> key = "test_g/test_subg"
    >>> with h5py.File(in_filename, 'w') as f:
    ...    g = f.create_group(key)
    ...    ds = g.create_dataset('a', data = np.array([5, 3, 2.]))
    >>> hdf5_copy(in_filename, key, out_filename, key)
    >>> with h5py.File(out_filename, 'r') as f:
    ...    assert_(key in f)
    >>> hdf5_copy(in_filename, key, out_filename, key)
    >>> with h5py.File(out_filename, 'r') as f:
    ...    assert_(key in f)
    >>> hdf5_copy(in_filename, key, out_filename, key, False)
    >>> with h5py.File(out_filename, 'r') as f:
    ...    assert_(key in f)
    
    '''
    if out_key is None: out_key = in_key
    with h5py.File(in_filename, 'r') as inf:
        assert_(in_key in inf, f'could not find {in_key} in {in_filename}')
        with h5py.File(out_filename, 'a') as outf:
            if out_key + '_tmp' in outf:
                del outf[out_key + '_tmp']
            # _logger.info(f'copying {in_key}')
            if out_key in outf:
                if skip_if_exists:
                    # _logger.info(f'{out_key} already exists in {out_filename}, skipping')
                    return
                # _logger.info(f'replacing {out_key} in {out_filename}')
                del outf[out_key]
            outf.copy(inf[in_key], outf, out_key + '_tmp')
            outf.move(out_key + '_tmp', out_key)
            outf.flush()


def get_temp_dir() -> str:
    if os.access('/tmp', os.W_OK):
        return '/tmp'
    else:
        return tempfile.gettempdir()


def test_hdf5_to_df():
    size = int(100)
    a = np.random.randint(0, 10000, size)
    b = a * 1.1
    letters = np.random.choice(list(string.ascii_letters), (size, 5))
    c = np.empty(size, dtype='O')
    for i, row in enumerate(letters):
        c[i] = ''.join(row)
    c[1] = None
    d = (a * 1000).astype('M8[m]')
    temp_dir = get_temp_dir()
    # os.remove(f'{temp_dir}/test.hdf5')
    if os.path.isfile(f'{temp_dir}/test.hdf5'): os.remove(f'{temp_dir}/test.hdf5')
    np_arrays_to_hdf5({"b": b, "a": a, "c": c, "d": d}, f'{temp_dir}/test.hdf5', 'key1/key2')
    file_size = os.path.getsize(f'{temp_dir}/test.hdf5')
    print(f"file size: {file_size / 1e3:.0f} KB")
    
    hdf5_repack(f'{temp_dir}/test.hdf5', f'{temp_dir}/test.hdf5.tmp')
    if os.path.isfile(f'{temp_dir}/test.hdf5'): os.remove(f'{temp_dir}/test.hdf5')
    os.rename(f'{temp_dir}/test.hdf5.tmp', f'{temp_dir}/test.hdf5')
    file_size = os.path.getsize(f'{temp_dir}/test.hdf5')
    print(f"file size: {file_size / 1e3:.0f} KB")
    assert_(file_size > 10000 and file_size < 14000, f'invalid file size: {file_size}')

    if os.path.isfile(f'{temp_dir}/test.hdf5'): os.remove(f'{temp_dir}/test.hdf5')
    df_in = pd.DataFrame(dict(a=a, b=b, c=c, d=d))
    df_to_hdf5(df_in, f'{temp_dir}/test.hdf5', 'key1/key2', dtypes={'d': 'M8[m]'})
    df_out = hdf5_to_df(f'{temp_dir}/test.hdf5', 'key1/key2')
    df_out.c = np.where(df_out.c == '', None, df_out.c)
    from pandas.testing import assert_frame_equal
    assert_frame_equal(df_in, df_out)


if __name__ == '__main__':
    test_hdf5_to_df()
    import doctest
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS)
# $$_end_code
