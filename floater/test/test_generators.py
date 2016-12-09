from floater import generators as gen
import numpy as np
import os
import pytest

# these are all combinations of (xlim, ylim, dx, dy) that will be fed to the
# different tests
domain_geometries = [
    # xlim, ylim, dx, dy, model_grid
    ((0,10), (0,20), 1, 1, None),
    ((10,20), (20,30), 1, 1, None),
    ((0.,10.), (0.,20.), 1., 1., None),
    ((10.,20.), (20,30.), 1., 1., None),
    ((10.,20.), (20,30.), 0.1, 0.1, None),
    # Anirban's example
    # https://github.com/rabernat/floater/issues/3
    ((-60.,-50.), (33.,40.5), 0.02, 0.015, None)
]

def _generate_model_grid(dg):
    xlim, ylim, dx, dy, _ = dg
    # use half the resoltion of the float set for the mask
    Nx = int((xlim[1] - xlim[0]) / dx)/2
    Ny = int((ylim[1] - ylim[0]) / dy)/2
    lon = np.linspace(xlim[0], xlim[1], Nx)
    lat = np.linspace(ylim[0], ylim[1], Ny)
    mask = np.ones((Ny, Nx), dtype='bool')
    # mask the upper half of the domain
    mask[Ny/2:] = False
    return {'lon': lon, 'lat': lat, 'land_mask': mask}

domain_geometries_with_land = [
    dg[:-1] + (_generate_model_grid(dg),) for dg in domain_geometries
]


@pytest.fixture(params=domain_geometries)
def fs(request):
    xlim, ylim, dx, dy, _ = request.param
    return gen.FloatSet(xlim, ylim, dx, dy)


@pytest.fixture(params=domain_geometries_with_land)
def fs_with_land(request):
    xlim, ylim, dx, dy, model_grid = request.param
    return gen.FloatSet(xlim, ylim, dx, dy, model_grid=model_grid)


@pytest.fixture(params=(domain_geometries+domain_geometries_with_land))
def fs_all(request):
    xlim, ylim, dx, dy, model_grid = request.param
    return gen.FloatSet(xlim, ylim, dx, dy, model_grid=model_grid)


def test_float_set_shape(fs):
    """Make sure we can create FloatSet objects correctly."""
    # check shape
    nx, ny = (fs.xlim[1]-fs.xlim[0])/fs.dx, (fs.ylim[1]-fs.ylim[0])/fs.dy
    assert (fs.Nx, fs.Ny) == (nx, ny)


def test_rectmesh(fs):
    """Make sure the rectangular grid looks right."""

    x, y = fs.get_rectmesh()
    assert x.shape == (fs.Ny, fs.Nx)
    assert y.shape == (fs.Ny, fs.Nx)
    # make sure the first point is where we expect it
    assert np.allclose(x[0,0], fs.xlim[0] + fs.dx/2.)
    assert np.allclose(y[0,0], fs.ylim[0] + fs.dy/2.)
    # make sure the last point is where we expect it
    assert np.allclose(x[-1,-1], fs.xlim[1] - fs.dx/2.)
    assert np.allclose(y[-1,-1], fs.ylim[1] - fs.dy/2.)
    # make sure things are "rectangular"
    assert np.allclose(x[0], x[1])

def test_hexmesh(fs):
    """Make sure the rectangular grid looks right."""

    x, y = fs.get_hexmesh()
    assert x.shape == (fs.Ny, fs.Nx)
    assert y.shape == (fs.Ny, fs.Nx)
    # make sure the first point is where we expect it
    assert np.allclose(x[0,0], fs.xlim[0] + 3*fs.dx/4.)
    assert np.allclose(y[0,0], fs.ylim[0] + fs.dy/2.)
    # make sure things are "rectangular"
    assert np.allclose(x[0], x[1] + fs.dx/2)

def test_land_mask(fs_with_land):
    """Verifies that the float grid excludes the masked regions properly."""

    fs = fs_with_land
    test_model = fs.model_grid
    # the top half of the domain should be masked
    grid_lat = test_model['lat']
    coast_lat = grid_lat[len(grid_lat)/2]

    #rect grid test
    float_x, float_y = fs.get_rectmesh()

    # check that all floats are within domain
    assert np.all((float_x >= fs.xlim[0] ) & ( float_x <= fs.xlim[1] ))
    assert np.all((float_y >= fs.ylim[0] ) & ( float_y <= fs.ylim[1] ))

    # check that the floats are beneath the coast (margin of error 2*dy)
    assert np.all(float_y <= coast_lat+2*fs.dy)

    num_floats = len(float_x)
    assert num_floats == len(float_y)
    #check that there are several floats
    assert num_floats > 1
    # check that something has been masked
    assert num_floats < (fs.Nx*fs.Ny)

    #hex grid test
    float_x, float_y = fs.get_hexmesh()

    # check that all floats are within domain
    assert np.all((float_x >= fs.xlim[0]) & (float_x <= fs.xlim[1]))
    assert np.all((float_y >= fs.ylim[0]) & (float_y <= fs.ylim[1]))

    # check that the floats are beneath the coast (margin of error 2*dy)
    assert np.all(float_y <= coast_lat+2*fs.dy)

    #check that there are several floats
    assert len(float_x) > 1
    assert len(float_y) > 1

def test_area(fs_all):
    """Kind of just a placeholder. Doesn't check actual values."""

    fs = fs_all
    a = fs.parcel_area()
    assert np.all(a > 0)

def test_to_mitgcm_format(fs_all, tmpdir):

    fs = fs_all
    for mesh in ['rect', 'hex']:
        if mesh=='rect':
            xx, yy = fs.get_rectmesh()
        else:
            xx, yy = fs.get_hexmesh()
        num_floats = len(xx.ravel())
        for iup in [-1, 0, 1]:
            filename = str(tmpdir.join('ini_flt_pos_%s_%g.bin' % (mesh, iup)))
            fs.to_mitgcm_format(filename, mesh=mesh, iup=iup)
            # check the file exists
            assert os.path.exists(filename)
            # check the file has the correct length
            array = np.fromfile(filename, dtype='>f4')
            assert len(array)==(num_floats + 1 )* 9
            # check that the number of floats written to the file matches
            # the actual number of floats
            array = array.reshape(-1,9)
            assert int(array[0,0]) == num_floats