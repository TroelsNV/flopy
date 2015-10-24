import os
import copy
import numpy as np
from datetime import datetime

# globals
FILLVALUE = -99999.9
ITMUNI = {0:"undefined",1:"seconds",2:"minutes",3:"hours",4:"days",5:"years"}
LENUNI = {0:"undefined",1:"feet",2:"meters",3:"centimeters"}
PRECISION_STRS = ["f4","f8","i4"]


class Logger(object):
    """ a basic class for logging events during the linear analysis calculations
        if filename is passed, then an file handle is opened
    Parameters:
    ----------
        filename (bool or string): if string, it is the log file to write
            if a bool, then log is written to the screen
        echo (bool): a flag to force screen output
    Attributes:
    ----------
        items (dict) : tracks when something is started.  If a log entry is
            not in items, then it is treated as a new entry with the string
            being the key and the datetime as the value.  If a log entry is
            in items, then the end time and delta time are written and
            the item is popped from the keys

    """
    def __init__(self,filename, echo=False):
        self.items = {}
        self.echo = bool(echo)
        if filename == True:
            self.echo = True
            self.filename = None
        elif filename:
            self.f = open(filename, 'w', 0) #unbuffered
            self.t = datetime.now()
            self.log("opening " + str(filename) + " for logging")
        else:
            self.filename = None


    def log(self,phrase):
        """log something that happened
        Parameters:
        ----------
            phrase (str) : the thing that happened
        """
        pass
        t = datetime.now()
        if phrase in self.items.keys():
            s = str(t) + ' finished: ' + str(phrase) + ", took: " + \
                str(t - self.items[phrase]) + '\n'
            if self.echo:
                print(s,)
            if self.filename:
                self.f.write(s)
            self.items.pop(phrase)
        else:
            s = str(t) + ' starting: ' + str(phrase) + '\n'
            if self.echo:
                print(s,)
            if self.filename:
                self.f.write(s)
            self.items[phrase] = copy.deepcopy(t)

    def warn(self,message):
        """write a warning to the log file
        Parameters:
        ----------
            message (str) : the warning text

        """
        s = str(datetime.now()) + " WARNING: " + message + '\n'
        if self.echo:
            print(s,)
        if self.filename:
            self.f.write(s)


class NetCdf(object):
    """ support for writing a netCDF4 compliant file from a flopy model
     Parameters:
     ----------
        output_filename (str) : the name of the .nc file to write

        ml : flopy model instance

        time_values : the entires for the time dimension
            if not None, the constructor will initialize
            the file.  If None, the perlen array of ModflowDis
             will be used

        verbose : if True, stdout is verbose.  If str, then a log file
            is written to the verbose file

    Note:
    ----
        this class relies heavily on the ModflowDis object,
        including these attributes:
                    lenuni
                    itmuni
                    epsg_str
                    start_datetime
                    sr (SpatialReference)
        make sure these attributes have meaningful values

    """

    def __init__(self,output_filename,ml,time_values=None,verbose=False):

        assert output_filename.lower().endswith(".nc")
        if verbose is None:
            verbose = ml.verbose
        self.logger = Logger(verbose)
        self.log = self.logger.log
        if os.path.exists(output_filename):
            self.logger.warn("removing existing nc file: "+output_filename)
            os.remove(output_filename)
        self.output_filename = output_filename

        assert ml.dis != None
        self.ml = ml
        self.shape = (self.ml.nlay,self.ml.nrow,self.ml.ncol)

        import pandas as pd
        self.start_datetime = pd.to_datetime(self.ml.dis.start_datetime).\
                                  isoformat().split('.')[0].split('+')[0] + "Z"

        self.grid_units = LENUNI[self.ml.dis.lenuni]
        assert self.grid_units in ["feet","meters"],\
            "unsupported length units: " + self.grid_units

        self.time_units = ITMUNI[self.ml.dis.itmuni]

        # this gives us confidence that every NetCdf instance has the same attributes
        self.log("initializing attributes")
        self._initialize_attributes()
        self.log("initializing attributes")

        # if time_values were passed, lets get things going
        if time_values is not None:
            self.log("time_values != None, initializing file")
            self.initialize_file(time_values=time_values)
            self.log("time_values != None, initializing file")


    def write(self):
        """ write the nc object to disk"""
        self.log("writing nc file")
        assert self.nc is not None,"netcdf.write() error: nc file not initialized"

        # write any new attributes that have been set since initializing the file
        for k,v in self.global_attributes.items():
            try:
                if self.nc.attributes.get(k) is not None:
                    self.nc.setncattr(k,v)
            except Exception as e:
                self.logger.warn('error setting global attribute {0}'.format(k))

        self.nc.sync()
        self.nc.close()
        self.log("writing nc file")


    def _initialize_attributes(self):
        """ private method to initial the attributes
            of the NetCdf instance
        """
        assert "nc" not in self.__dict__.keys(),\
            "NetCdf._initialize_attributes() error: nc attribute already set"

        self.nc_epsg_str = 'epsg:4326'
        self.nc_semi_major = float(6378137.0)
        self.nc_inverse_flat = float(298.257223563)

        self.global_attributes = {}

        self.fillvalue = FILLVALUE

        # initialize attributes
        self.grid_crs = None
        self.zs = None
        self.ys = None
        self.xs = None

        self.chunks = {"time": None}
        self.chunks["x"] = int(self.shape[1] / 4) + 1
        self.chunks["y"] = int(self.shape[2] / 4) + 1
        self.chunks["z"] = self.shape[0]
        self.chunks["layer"] = self.shape[0]

        self.nc = None



    def initialize_geometry(self):
        """ initialize the geometric information
            needed for the netcdf file
        """
        try:
            from pyproj import Proj, transform
        except Exception as e:
            raise Exception("NetCdf error importing pyproj module:\n" + str(e))

        self.grid_crs = Proj(init=self.ml.dis.sr.epsg_str)

        self.zs = -1.0 * self.ml.dis.zcentroids[:,:,::-1]

        ys = np.flipud(self.ml.dis.sr.ycentergrid)
        xs = np.fliplr(self.ml.dis.sr.xcentergrid)

        if self.grid_units.lower().startswith("f"):
            ys /= 3.281
            xs /= 3.281

        # Transform to a known CRS
        nc_crs = Proj(init=self.nc_epsg_str)

        self.xs, self.ys = transform(self.grid_crs,nc_crs,xs,ys)

    def initialize_file(self,time_values=None):
        """ initialize the netcdf instance, including global attributes,
            dimensions, and grid information

        Parameters:
        ----------

            time_values : list of times to use as time dimension
                entries.  If none, then use the times in
                self.model.dis.perlen and self.start_datetime

        """
        if self.nc is not None:
            raise Exception("nc file already initialized")

        if self.grid_crs is None:
            self.log("initializing geometry")
            self.initialize_geometry()
            self.log("initializing geometry")
        try:
            import netCDF4
        except Exception as e:
            self.logger.warn("error importing netCDF module")
            raise Exception("NetCdf error importing netCDF4 module:\n" + str(e))

        # open the file for writing
        self.nc = netCDF4.Dataset(self.output_filename, "w")

        # write some attributes
        self.log("setting standard attributes")
        self.nc.setncattr("Conventions", "CF-1.6")
        self.nc.setncattr("date_created", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:00Z"))
        self.nc.setncattr("geospatial_vertical_positive",   "up")
        min_vertical = np.min(self.zs)
        max_vertical = np.max(self.zs)
        self.nc.setncattr("geospatial_vertical_min", min_vertical)
        self.nc.setncattr("geospatial_vertical_max", max_vertical)
        self.nc.setncattr("geospatial_vertical_resolution", "variable")
        self.nc.setncattr("featureType", "Grid")
        self.nc.setncattr("origin_x", self.ml.dis.sr.xul)
        self.nc.setncattr("origin_y", self.ml.dis.sr.yul)
        self.nc.setncattr("origin_crs", self.ml.dis.sr.epsg_str)
        self.nc.setncattr("grid_rotation_from_origin", self.ml.dis.sr.rotation)
        for k, v in self.global_attributes.items():
            try:
                self.nc.setself.ncattr(k, v)
            except:
                self.logger.warn("error setting global attribute {0}".format(k))
        self.global_attributes = {}
        self.log("setting standard attributes")
        # spatial dimensions

        self.nc.createDimension('x', self.shape[2])
        self.nc.createDimension('y', self.shape[1])
        self.nc.createDimension('layer', self.shape[0])

        # Metadata variables
        crs = self.nc.createVariable("crs", "i4")
        crs.long_name = "see http://www.opengis.net for more info"
        crs.epsg_code = self.nc_epsg_str
        crs.semi_major_axis = self.nc_semi_major
        crs.inverse_flattening = self.nc_inverse_flat


        # time
        if time_values is None:
            time_values = np.cumsum(self.ml.dis.perlen)
        self.chunks["time"] = min(len(time_values), 100)
        self.nc.createDimension("time", len(time_values))

        attribs = {"units":"{0} since {1}".format(self.time_units, self.start_datetime),
                   "standard_name": "time", "long_name": "time", "calendar": "gregorian"}
        time = self.create_variable("time",attribs,precision_str="f8",dimensions=("time",))
        time[:] = np.asarray(time_values)

        # Latitude
        attribs = {"units":"degrees_north","standard_name":"latitude",
                   "long_name":"latitude","axis":"Y"}
        lat = self.create_variable("latitude",attribs,dimensions=("x","y"))
        lat[:] = self.ys

        # Longitude
        attribs = {"units":"degrees_east","standard_name":"longitude",
                   "long_name":"longitude","axis":"X"}
        lon = self.create_variable("longitude",attribs,dimensions=("x","y"))
        lon[:] = self.xs

        # Elevation
        attribs = {"units":"meters","standard_name":"elevation",
                   "long_name":"elevation","axis":"Z",
                   "valid_min":min_vertical,"valid_max":max_vertical,
                   "positive":"down"}
        elev = self.create_variable("elevation",attribs,dimensions=("layer","x","y"))
        elev[:] = self.zs

        # layer
        attribs = {"units":"","standard_name":"layer","long_name":"layer",
                   "positive":"down","axis":"Z"}
        lay = self.create_variable("layer",attribs,dimensions=("layer",))
        lay[:] = np.arange(0, self.shape[0])

        # delc
        attribs = {"units":"meters","long_names":"row spacing",
                   "origin_x":self.ml.dis.sr.xul,
                   "origin_y":self.ml.dis.sr.yul,
                   "origin_crs":self.nc_epsg_str}
        delc = self.create_variable('delc', attribs, dimensions=('y',))
        if self.grid_units.lower().startswith('f'):
            delc[:] = self.ml.dis.delc.array[::-1] * 0.3048
        else:
            delc[:] = self.ml.dis.delc.array[::-1]
        if self.ml.dis.sr.rotation != 0:
            delc.comments = "This is the column spacing that applied to the UNROTATED grid. " +\
                            "This grid HAS been rotated before being saved to NetCDF. " +\
                            "To compute the unrotated grid, use the origin point and this array."

        # delr
        attribs = {"units":"meters","long_names":"col spacing",
                   "origin_x":self.ml.dis.sr.xul,
                   "origin_y":self.ml.dis.sr.yul,
                   "origin_crs":self.nc_epsg_str}
        delr = self.create_variable('delr', attribs, dimensions=('x',))
        if self.grid_units.lower().startswith('f'):
            delr[:] = self.ml.dis.delr.array[::-1] * 0.3048
        else:
            delr[:] = self.ml.dis.delr.array[::-1]
        if self.ml.dis.sr.rotation != 0:
            delr.comments = "This is the row spacing that applied to the UNROTATED grid. " +\
                            "This grid HAS been rotated before being saved to NetCDF. " +\
                            "To compute the unrotated grid, use the origin point and this array."

        # Workaround for CF/CDM.
        # http://www.unidata.ucar.edu/software/thredds/current/netcdf-java/reference/StandardCoordinateTransforms.html
        # "explicit_field"
        exp = self.nc.createVariable('VerticalTransform', 'S1')
        exp.transform_name = "explicit_field"
        exp.existingDataField = "elevation"
        exp._CoordinateTransformType = "vertical"
        exp._CoordinateAxes = "layer"

    def create_variable(self, name, attributes, precision_str='f4',
                        dimensions=("time", "layer", "x", "y")):
        """ create a new variable in the netcdf object

        Parameters:
        ----------
            name (str) : the name of the variable

            attributes (dict) : attributes to add to the new variable

            precision_str (str) : netcdf-compliant string. e.g. f4

            dimensions (tuple) : which dimensions the variable applies to
                default : ("time","layer","x","y")

        Returns:
        -------
            nc variable

        Raises:
        ------
            AssertionError if precision_str not right
            AssertionError if variable name already in netcdf object
            AssertionError if one of more dimensions do not exist

        """

        self.log("creating variable: " + str(name))
        assert precision_str in PRECISION_STRS,\
            "netcdf.create_variable() error: precision string {0} not in {1}".\
                format(precision_str,PRECISION_STRS)

        if self.nc is None:
            self.initialize_file()

        # check that the requested dimension exists and
        # build up the chuck sizes
        chunks = []
        for dimension in dimensions:
            assert self.nc.dimensions.get(dimension) is not None,\
                "netcdf.create_variable() dimension not found:" + dimension
            chunk = self.chunks[dimension]
            assert chunk is not None,\
                "netcdf.create_variable() chunk size of {0} is None in self.chunks".\
                format(dimension)
            chunks.append(chunk)

        # Normalize variable name
        name = name.replace('.', '_').replace(' ', '_').replace('-', '_')
        assert self.nc.variables.get(name) is None,\
            "netcdf.create_variable error: variable already exists:" + name

        var = self.nc.createVariable(name, precision_str, dimensions,
                                     fill_value=self.fillvalue, zlib=True,
                                     chunksizes=tuple(chunks))

        for k, v in attributes.items():
            try:
                var.setncattr(k, v)
            except:
                self.logger.warn("error setting attribute" +\
                                 "{0} for variable {1}".format(k,name))
        self.log("creating variable: " + str(name))
        return var



