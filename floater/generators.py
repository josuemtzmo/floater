"""For generating grids of floats."""

from __future__ import print_function

import numpy as np
import pandas as pd
import pickle
import xarray as xr
from scipy.spatial import cKDTree


def geo_to_xyz(geo_cord):
    lon_deg, lat_deg,depth =np.vsplit(geo_cord,3)
    earthrad=6371000
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    x =  (earthrad+depth)*np.cos(lat)*np.cos(lon)
    y =  (earthrad+depth)*np.cos(lat)*np.sin(lon)
    z =  (earthrad+depth)*np.sin(lat)
    xyz_cord = np.squeeze(np.transpose(np.array((x,y,z)),(2,0,1)))
    return xyz_cord

def xyz_to_geo(xyz_coord):
    x,y,z = xyz_coord.transpose()
    lat = np.arcsin(z)
    lon = np.arctan2(y,x)
    lon_deg = np.degrees(lon)
    lat_deg = np.degrees(lat)
    geo_cord = np.transpose(np.array((lon_deg, lat_deg)))
    return geo_cord


class FloatSet(object):
    """Represents a set of initial float positions on a regular grid."""

    def __init__(self, xlim=None, ylim=None, dx=1., dy=1., model_grid=None, load_path=None, zvect=None):
        """Initialize FloatSet according to specified rectangular grid geometry.

        PARAMETERS
        ----------
        xlim : tuple of two floats
            minimum and maximum x coordinate of cell vertices
        ylim : tuple of two floats
            minimum and maximum y coordinate of cell vertices
        zvect : 1d array of depths
        dx : float
            grid spacing in x direction
        dy : float
            grid spacing in y direction
        model_grid : dictionary
            the following key value pairs are expected
            'land_mask': np.ndarray of bools
                2d array of dimensions in C order: shape==(len(lat), len(lon))
                An element is True iff the corresponding tracer cell grid point
                is unmasked (ocean)
                OR
                3d array of dimensions in C order shape==(len(depth),len(lat), len(lon))
            'lon': 1d array of the mask grid longitudes
            'lat': 1d array of the mask grid latitudes
            'rc' : 1d array of mask depths

        load_path : str
            The filename to load a saved floatset object from
            (e.g. 'floatset.pkl')
        """

        if load_path is None:
            if not len(xlim)==2 and len(ylim)==2:
                raise ValueError('xlim and ylim should both be length 2.')
            self.xlim = [float(x) for x in xlim]
            self.ylim = [float(y) for y in ylim]
            self.Lx = xlim[1] - xlim[0]
            self.Ly = ylim[1] - ylim[0]
            if not (float(self.Lx)/float(dx)).is_integer():
                raise ValueError("Lx is not divisible evenly by dx")
            if not (float(self.Ly)/float(dy)).is_integer():
                raise ValueError("Ly is not divisible evenly by dy")
            self.dx = float(dx)
            self.dy = float(dy)
            self.Nx = int(self.Lx / self.dx)
            self.Ny = int(self.Ly / self.dy)
            self.x = self.xlim[0] + self.dx * np.arange(self.Nx) + self.dx/2
            self.y = self.ylim[0] + self.dy * np.arange(self.Ny) + self.dy/2
            if zvect is not None:
                self.zvect = zvect
                self.Nz=zvect.size
                self.dims=3
            else:
                self.Nz=1
                self.zvect=[-0.5]
                self.dims=2
            self.model_grid = model_grid
        else:
            self.from_pickle(load_path)



    def get_rectmesh(self):
        """Get the coordinates of the float positions in a rectangualr mesh.

        RETURNS
        -------
        x : np.ndarray
            1D array of float x coordinates
        y : np.ndarray
            1D array of float y coordinates
        z : np.ndarray
            1D array of float z coordinates
        """
        if self.dims==3:
            xx, yy, zz= np.meshgrid(self.x, self.y,self.zvect)
            if self.model_grid is not None:
                xx, yy, zz = self.subset_floats_from_mask(xx, yy,zz)
            return xx,yy,zz
        else:
            xx, yy = np.meshgrid(self.x, self.y)
            if self.model_grid is not None:
                zz=np.ones(xx.size)*-0.5
                xx, yy = self.subset_floats_from_mask(xx, yy, zz)
            return xx, yy


    def get_hexmesh(self):
        """Get the coordinates of the float positions in a hexagonal mesh.

        RETURNS
        -------
        x : np.ndarray
            1D array of float x coordinates
        y : np.ndarray
            1D array of float y coordinates
        z : np.ndarray
            1D array of float z coordinates
        """
        if self.dims==3:
            xx, yy, zz = np.meshgrid(self.x, self.y,self.zvect)
            # modify to be even-R horizontal offset
            xx[::2] += self.dx/4
            xx[1::2] -= self.dx/4
            if self.model_grid is not None:
                xx, yy, zz = self.subset_floats_from_mask(xx, yy, zz)
            return xx,yy,zz
        else:
            xx, yy = np.meshgrid(self.x, self.y)
            # modify to be even-R horizontal offset 
            xx[::2] += self.dx/4
            xx[1::2] -= self.dx/4

            if self.model_grid is not None:
                zz=np.ones(xx.size)*-0.5
                xx, yy = self.subset_floats_from_mask(xx, yy, zz)
            return xx, yy


    def npart_index_to_ndarray(self, data, npart):
        """Grid the data according to its npart (particle id)

        PARAMETERS
        ----------
        data : 1D array
            The data to be gridded
        npart : 1D array
            The particle ids
        """
        pass

    def parcel_area(self, latlon=True):
        """Get the area of each parcel."""

        if latlon==False:
            # cartesian grid
            return self.dx * self.dy
        else:
            R = 6.371e6
            if self.dims==2:
                lon, lat = self.get_rectmesh()
            else:
                lon, lat,depth = self.get_rectmesh()
            dy = R * np.radians(self.dy)
            dx = R * np.radians(self.dx) * np.cos(np.radians(lat))
            # old code, wrong!
            #dy = self.dy * R / 360.
            #dx = dy * np.cos(np.radians(lat)) * self.dx * R / 360.
            return dx * dy

    def to_mitgcm_format(self, filename, tstart=0, iup=0, mesh='rect',
                         read_binary_prec=64):
        """Output floatset data in MITgcm format

        PARAMETERS
        ----------
        filename : str
            The filename to save the floatset data in
            (e.g.float.ini.pos.hex.bin)
        tstart : float
            time for float initialisation (default = 0)
        iup : int
            flag if the float
                - should profile ( > 0 = return cycle (in s) to surface)
                - remain at depth ( = 0 )
                - is a 3D float ( = -1 )
                - should be advected WITHOUT additional noise (= -2 );
                    (this implies that the float is non-profiling)
                - is a mooring ( = -3 ); i.e. the float is not advected
        mesh : {'rect', 'hex'}
            - 'rect' : rectangular cartesian
            - 'hex' : hexagonal
        read_binary_prec : {32, 64}
            data precision for binary file (should match MITgcm data file)
        """

        if read_binary_prec==32:
            dtype = np.dtype('>f4')
        elif read_binary_prec==64:
            dtype = np.dtype('>f8')
        else:
            raise ValueError('read_binary_prec should be 32 or 64; '
                             'got %g' % read_binary_prec )

        if mesh == 'hex' and self.dims==3:
            xx, yy, zz = self.get_hexmesh()
        elif mesh == 'hex' and self.dims==2:
            xx, yy = self.get_hexmesh()
        elif self.dims==3:
            xx, yy, zz = self.get_rectmesh()
        else:
            xx, yy = self.get_rectmesh()
        myx = xx

        ini_times = 1

        # initial positions
        lon = myx.ravel()
        lat = yy.ravel()
        if self.dims==2:
            kpart=-0.5
        else:
            kpart=zz.ravel()

        # other float properties

        # kpart: depth of float release in meters, depth is negative, i.e. -1500
        # for 1500 m
        #kpart = -0.5

        # kfloat: target level of float (??)
        kfloat = -0.5

        # itop: time of float at the surface (in s)
        itop = 0
        
        # end time of integration of float (in s); note if tend = 1 floats are
        # integrated till the end of the integration;
        tend = -1;

        # number of floats
        N = len(lon)

        output_dtype = np.dtype(dtype)
        # for all the float data
        flt_matrix = np.zeros((N+1,9), dtype=output_dtype)

        flt_matrix[1:,0] = np.arange(N)+1
        flt_matrix[1:,1] = tstart
        flt_matrix[1:,2] = lon
        flt_matrix[1:,3] = lat
        flt_matrix[1:,4] = kpart
        flt_matrix[1:,5] = kfloat
        flt_matrix[1:,6] = iup
        flt_matrix[1:,7] = itop
        flt_matrix[1:,8] = tend

        # first line in initialization file contains a record with
        # - the number of floats on that tile in the first record
        # - the total number of floats in the sixth record

        flt_matrix[0,0] = N;
        flt_matrix[0,1] = -1
        flt_matrix[0,4] = -1
        flt_matrix[0,5] = N
        flt_matrix[0,8] = -1

        return flt_matrix.tofile(filename)

    def to_pickle(self, filename='./floatset.pkl'):
        """Write out floatset data in pickled format

        PARAMETERS
        ----------
        filename : str
            The filename to save the floatset data in
            (e.g. 'floatset.pkl')
        """

        with open(filename, 'wb') as file:
            pickle.dump(self, file, -1)

    def from_pickle(self, filename='./floatset.pkl'):
        """Sets attributes equal to saved FloatSet object in pickled format

        PARAMETERS
        ----------
        filename : str
            The filename to load in the saved floatset data from
            (e.g. 'floatset.pkl')
        """
        self.ocean_bools = None #instantiate bef. updating
        with open(filename, 'rb') as file:
            self.__dict__.update(pickle.load(file).__dict__)



    def subset_floats_from_mask(self, xx, yy, zz):
        """Eliminate float positions that are on land land mask.

        PARAMETERS
        ----------
        xx : arraylike
            float longitudes
        yy : arraylike
            float latitudes
        zz  :  arraylike
            float depths
        model_grid : dictionary
            the following key value pairs are expected
                'land_mask': np.ndarray of bools
                    2d array of dimensions in C order: shape==(len(lat), len(lon))
                    An element is True iff the corresponding tracer cell grid point
                    is unmasked (ocean)
                    OR 3d array
                'lon': 1d array of the mask grid longitudes
                'lat': 1d array of the mask grid latitudes
                'rc': 1d array of mask grid depths
        RETURNS
        -------
        xx_masked, yy_masked, zz_masked: np.ndarray
            1D arrays of float coordinates subarrays:
        """

        xx = xx.ravel()
        yy = yy.ravel()
        zz = zz.ravel()

        mask_lon = self.model_grid['lon']
        mask_lat = self.model_grid['lat']
        land_mask = self.model_grid['land_mask']
        if "rc" in self.model_grid:
            mask_depth = self.model_grid['rc']
        else:
            mask_depth=[-0.5]
            land_mask=np.expand_dims(land_mask,axis=2)
        # we require the array to be using using C order
        assert land_mask.shape[0:2] == (len(mask_lat), len(mask_lon))

        # fast cartesian product
        mask_geo = np.stack(np.meshgrid(mask_lon, mask_lat,mask_depth))
        mask_geo = mask_geo.reshape(3,-1)

        mask_bool_flat = land_mask.ravel()
        mask_xyz = geo_to_xyz(mask_geo)
        # a KDTree of the mask data in xyz form
        mask_tree = cKDTree(mask_xyz)
        floats_geo = np.array([xx.ravel(), yy.ravel(), zz.ravel()])
        # uniform hexagonal tiling
        queries_xyz = geo_to_xyz(floats_geo)
        # search for nearest neighbors
        dist, neighbor_indices = mask_tree.query(queries_xyz, n_jobs=-1)
        self.ocean_bools = np.take(mask_bool_flat, neighbor_indices.ravel()) # True -> neighbor is tracer ocean
        floats_ocean = floats_geo[:,np.nonzero(self.ocean_bools.astype('int'))].T
        floats_ocean=np.transpose(np.squeeze(floats_ocean))
        if self.dims==2:
            return floats_ocean[0:2,:]
        else:
            return floats_ocean


    def npart_to_2D_array(self, ds1d):
        """Constructs 2D Dataset from 1D DataArray/Dataset of single or multi-variable.

        PARAMETERS
        ----------
        ds1d : 1D DataArray/Dataset
            One-dimensional dataarray/dataset of physical variable(s) with dimension 'npart'

        RETURNS
        -------
        ds2d : 2D Dataset
            Two-dimensional dataset of physical variable(s) with dimensions 'y0' and 'x0'
        """

        Nx = self.Nx
        Ny = self.Ny
        Nz=self.Nz
        Nt = Nx*Ny*Nz
        if type(ds1d) == xr.core.dataarray.DataArray:
            ds1d = ds1d.to_dataset()
        index_dict = {'index': np.arange(1, Nt+1, dtype=np.int32)}
        var_list = list(ds1d.data_vars)
        var_dict = {var: np.full(Nt, np.nan, dtype=np.float32) for var in var_list}
        frame_dict = {}
        frame_dict.update(index_dict)
        frame_dict.update(var_dict)
        frame = pd.DataFrame(frame_dict)
        framei = frame.set_index('index')
        framei.columns = var_list
        if self.model_grid is not None:
            ocean_bools = self.ocean_bools
        else:
            ocean_bools = np.full(Nt, True, dtype=bool)
        da = ds1d.to_array().values
        axis_len = len(da.shape) - 2
        axis = tuple(np.arange(1, axis_len+1, dtype=np.int32))
        das = np.squeeze(da, axis=axis)
        dast = das.transpose()
        framei.loc[ocean_bools==True] = dast.astype(np.float32)
        dim_list = list(ds1d.dims)
        dim_list.remove('npart')
        dim_len = len(dim_list)
        new_shape = (1,)*dim_len + (Ny, Nx)
        new_dims = dim_list + ['y0', 'x0']
        data_vars = {}
        for var in var_list:
            frameir = framei[var].values
            frameir.shape = new_shape
            data_vars.update({var: (new_dims, frameir)})
        x0 = np.float32(self.x)
        y0 = np.float32(self.y)
        coords = {}
        coords.update({dim: ([dim], ds1d[dim].values) for dim in dim_list})
        coords.update({'y0': (['y0'], y0), 'x0': (['x0'], x0)})
        ds2d = xr.Dataset(data_vars=data_vars, coords=coords)
        return ds2d
