# -*- coding: utf-8 -*-
#
# ----------------------------------------------------- #
#                                                       #
#  This code is a part of T-matrix fitting project      #
#  Contributors:                                        #
#   L. Avakyan <laavakyan@sfedu.ru>                     #
#   K. Yablunovskiy <kirill-yablunovskii@mail.ru>       #
#                                                       #
# ----------------------------------------------------- #
"""
Based on heaviliy rewritten MSTM-GUI code
<URL:https://github.com/dmayerich/mstm-gui>
<https://git.stim.ee.uh.edu/optics/mstm-gui.git>
by Dr. David Mayerich

Optimized for spectral calculations (for many wavelengths)
in order to use for fitting to experiment
"""

import numpy as np
from numpy.random import lognormal
from scipy import interpolate
import subprocess
import os   # to delete files after calc.
import sys  # to check whether running on Linux or Windows
import datetime

try:
    from film_exctinction import gold_film_ex  # for gold film background
except:
    pass

import matplotlib.pyplot as plt

import time


class Profiler(object):
    """
    This class for benchmarking is from
    http://onesteptospace.blogspot.pt/2013/01/python.html
    Usage:
    >>> with Profiler() as p:
    >>>     // your code to be profiled here
    """
    def __enter__(self):
        self._startTime = time.time()

    def __exit__(self, type, value, traceback):
        print "Elapsed time: {:.3f} sec".format(time.time() - self._startTime)


class SPR(object):
    """ Class for calculation of surface plasmin resonance (SPR),
        running MSTM external code.
    """

    environment_material = 'Air'

    paramDict = {
      'number_spheres': 0,
      'sphere_position_file': '',          # radius, X,Y,Z [nm], n ,k
      'length_scale_factor': 1.0,          # 2π/λ[nm]
      'real_ref_index_scale_factor': 1.0,  # multiplier for spheres
      'imag_ref_index_scale_factor': 1.0,
      'real_chiral_factor': 0.0,           # chiral passive spheres
      'imag_chiral_factor': 0.0,
      'medium_real_ref_index': 1.0,        # refraction index of the environment
      'medium_imag_ref_index': 0.0,
      'medium_real_chiral_factor': 0.0,
      'medium_imag_chiral_factor': 0.0,
      'target_euler_angles_deg': [0.0, 0.0, 0.0],  # ignored for random orient. calc.

      'mie_epsilon': 1.0E-12,           # Convergence criterion for determining the number of orders in the Mie expansions. Negative value - number of orders.
      'translation_epsilon': 1.0E-8,    # Convergence criterion for estimating the maximum order of the cluster T matrix
      'solution_epsilon': 1.0E-8,       # Precision of linear equation system solution
      't_matrix_convergence_epsilon': 1.0E-6,
      'plane_wave_epsilon': 1E-3,       # Precision of expansion of incedent field (both for palne and gaussian waves)
      'iterations_per_correction': 20,  # ignored for big 'near_field_translation_distance'
      'max_number_iterations': 2000,    # with account of all iterations
      'near_field_translation_distance': 1.0E6,  # can be big real, small real or negative. TWEAK FOR PERFORMANCE
      'store_translation_matrix': 0,
      'fixed_or_random_orientation': 1,  # 0 - fixed, 1 - random
      'gaussian_beam_constant': 0,       # CB = 1/(k ω0). CB = 0 - plane wave
      'gaussian_beam_focal_point': [0.0, 0.0, 0.0],  # does not alters results for plane wave and random orientations
      'run_print_file': '',              # if balnk will use stdout
      'write_sphere_data': 0,            # 1 - detail, 0 - concise

      'output_file': 'test.dat',         # should change for each run

      'incident_or_target_frame': 0,     # Integer switch, relevant only for fixed orientation calculations
      'min_scattering_angle_deg': 0.0,
      'max_scattering_angle_deg': 180.0,
      'min_scattering_plane_angle_deg': 0.0,   # selects a plane for fixed orient.
      'max_scattering_plane_angle_deg': 0.0,   # selects a plane for fixed orient.
      'delta_scattering_angle_deg': 1.0,
      'calculate_near_field': 0,       # no near field calculations
      'calculate_t_matrix': 1,         # 1 - new calc., 0 - use old, 2 - continue calc
      't_matrix_file': 'tmatrix-temp.dat',
      'sm_number_processors': 10,      # actual number of procesor is minimum of this value and provided by mpi
    }

    local_keys = ['output_file', 'length_scale_factor', 'medium_real_ref_index', 'medium_imag_ref_index', 't_matrix_file']

    def __init__(self, wavelengths):
        self.wavelengths = wavelengths

    def set_spheres(self, spheres):
        self.spheres = spheres
        self.paramDict['number_spheres'] =  np.sum(self.spheres.a > 0)  # count only spheres with positive radii

    def simulate(self, outfn='extinction.txt'):
        if self.spheres.check_overlap():
            raise Exception('Spheres overlapping!')
        if isinstance(self.environment_material, Material):
            material = self.environment_material
        else:
            print(self.environment_material)
            material = Material(self.environment_material)
        outFID = open('scriptParams.inp', 'w')
        outFID.write('begin_comment\n')
        outFID.write('**********************************\n')
        outFID.write('  MSTM input for SPR calculation\n')
        outFID.write('  Generated by python script\n')
        outFID.write('  %s\n' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
        outFID.write('**********************************\n')
        outFID.write('end_comment\n')
        for key in self.paramDict.keys():
            if key not in self.local_keys:
                outFID.write(key + '\n')
                if isinstance(self.paramDict[key], basestring):
                    svalue = self.paramDict[key]
                else:
                    if isinstance(self.paramDict[key], list):
                        svalue = '  '.join(map(str, self.paramDict[key]))
                    else:
                        svalue = str(self.paramDict[key])
                    svalue = svalue.replace('e', 'd', 1)  # replace exponent sign to Fortran standart...
                outFID.write('%s \n' % svalue)

        for l in self.wavelengths:
            outFID.write('begin_comment\n')
            outFID.write('**********************************\n')
            outFID.write('  Wavelength  %.3f \n' % l)
            outFID.write('**********************************\n')
            outFID.write('end_comment\n')
            outFID.write('output_file\n')
            outFID.write('mstm_l%.0f.out\n' % (l*1000))  # filename like wavelength in picometers
            outFID.write('length_scale_factor\n')
            outFID.write('  %.6f\n' % (2.0 * 3.14159 / l))
            outFID.write('medium_real_ref_index\n')
            outFID.write('  %f\n'%material.get_n(l))
            outFID.write('medium_imag_ref_index\n')
            outFID.write('  %f\n'%material.get_k(l))

            outFID.write('sphere_sizes_and_positions\n')

            for i in xrange(len(self.spheres)):
                a = self.spheres.a[i]
                if a > 0:  # consider only positive radii
                    x = self.spheres.x[i]
                    y = self.spheres.y[i]
                    z = self.spheres.z[i]
                    n = self.spheres.materials[i].get_n(l)
                    k = self.spheres.materials[i].get_k(l)
                    outFID.write('  %.4f  %.4f  %.4f  %.4f  %.3f  %.3f \n' % (a, x, y, z, n, k))
            outFID.write('new_run\n')

        outFID.write('end_of_options\n')
        outFID.close()

        # run the binary
        if sys.platform == 'win32':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.call(['mstm.exe', 'scriptParams.inp'], startupinfo=si)
        else:
            subprocess.call( ['./run_mstm.sh'] )

        # parse the simulation results
        if self.paramDict['fixed_or_random_orientation'] == 0:  # fixed orientation
            self.extinction_par = []  # parallel polarization ( \hat \alpha ? )
            self.absorbtion_par = []
            self.scattering_par = []
            self.extinction_ort = []  # perpendicular polarization ( \hat \beta ? )
            self.absorbtion_ort = []
            self.scattering_ort = []
            for l in self.wavelengths:
                inFID = open('mstm_l%.0f.out' % (l*1000), 'r')
                while True:
                    line = inFID.readline()
                    if 'scattering matrix elements' in line:
                        break
                    elif 'parallel total ext, abs, scat efficiencies' in line:
                        values = map(float, inFID.readline().strip().split())
                        self.extinction_par.append(float(values[0]))
                        self.absorbtion_par.append(float(values[1]))
                        self.scattering_par.append(float(values[2]))
                    elif 'perpendicular total ext' in line:
                        values = map(float, inFID.readline().strip().split())
                        self.extinction_ort.append(float(values[0]))
                        self.absorbtion_ort.append(float(values[1]))
                        self.scattering_ort.append(float(values[2]))
                inFID.close()
                os.remove('mstm_l%.0f.out' % (l*1000))  # cleanup

            # save result to a file
            fout = open(outfn, 'w')
            fout.write('#Wavel.\tExt_par\tExt_ort\n')
            for i in range(len(self.wavelengths)):
                fout.write('%.4f\t%.8f\t%.8f\r\n' % (self.wavelengths[i],
                           self.extinction_par[i], self.extinction_ort[i]))
            fout.close()
            self.extinction_par = np.array(self.extinction_par)
            self.absorbtion_par = np.array(self.absorbtion_par)
            self.scattering_par = np.array(self.scattering_par)
            self.extinction_ort = np.array(self.extinction_ort)
            self.absorbtion_ort = np.array(self.absorbtion_ort)
            self.scattering_ort = np.array(self.scattering_ort)
            return self.wavelengths, (self.extinction_par+self.extinction_ort)
        else:    # random orientation
            self.extinction = []
            self.absorbtion = []
            self.scattering = []
            for l in self.wavelengths:
                inFID = open('mstm_l%.0f.out' % (l*1000), 'r')
                while True:
                    line = inFID.readline()
                    if 'scattering matrix elements' in line:
                        break
                    elif 'total ext, abs, scat efficiencies' in line:
                        values = map(float, inFID.readline().strip().split())
                        self.extinction.append(float(values[0]))
                        self.absorbtion.append(float(values[1]))
                        self.scattering.append(float(values[2]))
                inFID.close()
                os.remove('mstm_l%.0f.out' % (l*1000))  # cleanup
            # save result to a file
            fout = open(outfn, 'w')
            fout.write('#Wavel.\tExc.\n')
            for i in range(len(self.wavelengths)):
                fout.write('%.4f\t%.8f\r\n'%(self.wavelengths[i], self.extinction[i]))
            fout.close()
            self.extinction = np.array(self.extinction)
            self.absorbtion = np.array(self.absorbtion)
            self.scattering = np.array(self.scattering)
            return self.wavelengths, self.extinction

    def plot(self):
        plt.plot(self.wavelengths, self.extinction, 'r-', label='extinction')
        plt.show()

    def set_incident_field(self, fixed=False, azimuth_angle=0.0, polar_angle=0.0, polarization_angle=0.0):
        """
            Set incident field.
            fixed: bool
                True  - fixed oriented and polarized light
                False - average over all orientations and polarizations
            azimuth_angle, polar_angle: float (degrees)

            polarization_angle: float (degrees)
                polarization angle relative to the k-z palne.
                0 - X-polarized, 90 - Y-polarized (if azimuth and
                polar angles are zero).
        """
        if not fixed:
            self.paramDict["fixed_or_random_orientation"] = 1  # random
        else:
            self.paramDict["fixed_or_random_orientation"] = 0  # fixed
            self.paramDict["azimuth_angle_deg"] = polarization_angle
            self.paramDict["polar_angle_deg"] = polar_angle
            self.paramDict["polarization_angle_deg"] = polarization_angle


class Material(object):
    """
    Material class.
    Use get_n() and get_k() to obtain values of refraction indexes (real and imag)
    at arbitraty wavelength [nm]
    """
    def __init__(self, file_name):
        if isinstance(file_name, basestring):
            self.__name__ = 'Mat_%s' % os.path.basename(file_name)
        else:
            self.__name__ = 'Mat_%.3f' % file_name

        wl_min = 250   # 149.9
        wl_max = 1200  # 950.1
        wls = np.array([wl_min, wl_max])
        k   = np.array([0.0, 0.0])
        try:
            np.complex(file_name)
            is_complex = True
        except ValueError:
            is_complex = False
        if is_complex:
            refr_index = file_name
            nk = np.complex(file_name)
            n = np.array([np.real(nk), np.real(nk)])
            k = np.array([np.imag(nk), np.imag(nk)])
        else:
            if file_name.lower() == 'air':
                n = np.array([1.0, 1.0])
            elif file_name.lower() == 'water':
                n = np.array([1.33, 1.33])
            elif file_name.lower() == 'glass':
                n = np.array([1.66, 1.66])
            else:
                optical_constants = np.genfromtxt(file_name, names=True)
                # print optical_constants
                wls = optical_constants['lambda']
                if np.max(wls) < 10:  # wavelengths are in micrometers
                    wls = wls*1000   # convert to nm
                n = optical_constants['n']
                k = optical_constants['k']
                if wls[0] > wls[1]:    # wavelengths are sorted form bigger to smaller
                    wls = np.flipud(wls)  # resort required
                    n   = np.flipud(n)
                    k   = np.flipud(k)
                n   = n[wls > wl_min]
                k   = k[wls > wl_min]
                wls = wls[wls > wl_min]
                n   = n[wls < wl_max]
                k   = k[wls < wl_max]
                wls = wls[wls < wl_max]
        wl_step = np.abs(wls[1]-wls[0])
        if (wl_step>1.1) and (wl_step < 500):  # sparse mesh, suitable for cubic interpolation
            interp_kind = 'cubic'
        else:  # too dense or too sparse mesh, linear interpolation is needed
            interp_kind = 'linear'
        # print('Interpolation kind : %s'%interp_kind)
        self.get_n = interpolate.interp1d(wls, n, kind=interp_kind)
        self.get_k = interpolate.interp1d(wls, k, kind=interp_kind)

    def __str__(self):
        return self.__name__

    def plot(self, wls=None, fig=None, axs=None):
        """
        plot n and k dependence from wavelength

        Parameters:
        wls : np.array
            array of wavelength. If None then
            np.linspace(300, 800, 500) will be used.
        fig, axs : matplotlib objects
        """
        if wls is None:
            wls = np.linspace(300, 800, 500)
        flag = fig is None
        if flag:
            fig = plt.figure()
            axs = fig.add_subplot(111)
        axs.plot(wls, self.get_n(wls), label='Real')
        axs.plot(wls, self.get_k(wls), label='Imag')
        axs.set_ylabel('Refraction index')
        axs.set_xlabel('Wavelength, nm')
        axs.legend()
        if flag:
            plt.show()


#~ class MaterialManager():
    #~ """
    #~ Cache for materials, to decrease file i/o
    #~ """
    #~ def __init__(self, wavelengths):
        #~ self.materials = {}


class Spheres(object):
    """
    Abstract collection of spheres

    Fields:
    N : int
        number of spheres
    x, y, z: lists
        coordinates of sphere centers
    a : list
        sphere radii
    materials : list of Material objects
    """
    def __init__(self):
        self.N = 0
        self.x = []
        self.y = []
        self.z = []
        self.a = []  # radius
        self.materials = []

    def __len__(self):
        # return len(self.x)
        return self.N

    def check_overlap(self, eps=0.001):
        """
        Check if spheres are overlapping
        """
        result = False
        n = len(self.x)
        for i in xrange(n):
            for j in xrange(i+1, n):
                dx = abs(self.x[j] - self.x[i])
                dy = abs(self.y[j] - self.y[i])
                dz = abs(self.z[j] - self.z[i])
                Ri = self.a[i]
                Rj = self.a[j]
                dist = np.sqrt(dx * dx + dy * dy + dz * dz)
                if dist < Ri + Rj + eps:
                    # distance between spheres is less than sum of thier radii
                    # but there still can be nested spheres, check it
                    if Ri > Rj:
                        result = Ri < dist + Rj + eps
                    else:  # Rj < Ri
                        result = Rj < dist + Ri + eps
                if result:  # avoid unneeded steps
                    return True
        return result

    def append(self, sphere):
        """
        Append by data from SingleSphere object

        sphere : SingleSphere
        """
        self.a = np.append(self.a, sphere.a[0])
        self.x = np.append(self.x, sphere.x[0])
        self.y = np.append(self.y, sphere.y[0])
        self.z = np.append(self.z, sphere.z[0])
        self.materials.append(sphere.materials[0])
        self.N += 1

    def delete(self, i):
        self.a = np.delete(self.a, i)
        self.x = np.delete(self.x, i)
        self.y = np.delete(self.y, i)
        self.z = np.delete(self.z, i)
        self.materials.pop(i)
        self.N -= 1

    def extend(self, spheres):
        for i in xrange(len(spheres)):
            self.append(SingleSphere(spheres.x[i], spheres.y[i], spheres.z[i], spheres.a[i], spheres.materials[i]))

    def get_center(self, method=''):
        """
        calculate center of masses in assumption of uniform density
        method : {''|'mass'}
        """
        weights = np.ones(self.N)
        if method.lower() == 'mass':
            weights = self.a**3
        Xc = np.sum(np.dot(self.x, weights)) / np.sum(weights)
        Yc = np.sum(np.dot(self.y, weights)) / np.sum(weights)
        Zc = np.sum(np.dot(self.z, weights)) / np.sum(weights)
        return np.array((Xc, Yc, Zc))


class SingleSphere(Spheres):
    """
    Collection of spheres with only one sphere
    """
    def __init__(self, x, y, z, a, mat_filename='etaGold.txt'):
        self.N = 1
        self.x = np.array([x])
        self.y = np.array([y])
        self.z = np.array([z])
        self.a = np.array([a])
        if isinstance(mat_filename, Material):
            self.materials = [mat_filename]
        else:
            self.materials = [Material(mat_filename)]


class LogNormalSpheres(Spheres):
    """
    The set of spheres centered on the regular mesh
    with lognormal distributed sizes.
    In the case overlapping of the spheres the sizes
    will be regenerated
    """
    def __init__(self, N, mu, sigma, d, mat_filename='etaGold.txt'):
        """
        N: number of spheres
        mu and sigma: parameters of LogNormal distributions
        d: controls the spacing between spheres
        mat_filename: contains dielectric constants for the material
        """
        # estimate the box size:
        a = mu  # average sphere radius
        A = N**(1/3.) * (d + 2 * a)
        print('Box size estimated as: %.1f nm' % (A*1000.))
        # A = A*1.5
        Xc = []
        Yc = []
        Zc = []
        x = -A / 2.0
        while x < A / 2.0:
            y = -A / 2.0
            while y < A / 2.0:
                z = -A / 2.0
                while z < A / 2.0:
                    if (x * x + y * y + z * z < A * A / 4.0):
                        Xc.append(x)
                        Yc.append(y)
                        Zc.append(z)
                    z = z + (2 * a + d)
                y = y + (2 * a + d)
            x = x + (2 * a + d)
        print('Desired number of particles: %i' % N)
        print('Number of particles in a box: %i' % len(Xc))
        self.N = min([N, len(Xc)])
        print('Resulted number of particles: %i' % self.N)
        self.x = np.array(Xc)
        self.y = np.array(Yc)
        self.z = np.array(Zc)
        random_a = lognormal(np.log(mu), sigma, self.N)  # nm
        random_a = random_a
        self.a = np.array(random_a)
        if isinstance(mat_filename, Material):
            mat = mat_filename
        else:
            mat = Material(mat_filename)
        self.materials = [mat for i in xrange(self.N)]

class ExplicitSpheres (Spheres):
    def __init__(self, N=0, Xc=[], Yc=[], Zc=[], a=[], mat_filename='etaGold.txt'):
        """
        Create spheres according to explicit set of parameters:
        N: number of spheres
        Xc,Yc,Zc: arrays of coordinates of the spheres centers
        a: radiuses of the spheres
        mat_filename: file name of the material file cotaining
          refractive index dependence from wavelength.
          Can be single string or list of strings.

        If only first array Xc is supplied, than all data is zipped in it.
        i.e.: Xc = [X1, Y1, Z1, a1, ... XN, YN, ZN, aN]
        """
        super(ExplicitSpheres, self).__init__()
        self.N = N
        if N < len(Xc):  # data is zipped in Xc
            assert(N*4 == len(Xc))
            self.x = np.zeros(N)
            self.y = np.zeros(N)
            self.z = np.zeros(N)
            self.a = np.zeros(N)
            i = 0
            while i < len(Xc):
                self.x[i/4] = Xc[i+0]
                self.y[i/4] = Xc[i+1]
                self.z[i/4] = Xc[i+2]
                self.a[i/4] = abs(Xc[i+3])
                i = i + 4
        else:
            self.x = np.array(Xc)
            self.y = np.array(Yc)
            self.z = np.array(Zc)
            self.a = np.abs(np.array(a))

        if isinstance(mat_filename, (Material, basestring)):
            # one material filename for all spheres
            self._set_material(mat_filename)
        elif isinstance(mat_filename, list):
            # list of material filenames for all spheres
            if len(mat_filename) == 1:
                self._set_material(mat_filename[0])
            else:
                assert(len(mat_filename) == self.N)
                for mat_fn in mat_filename:
                    # TODO: use material manager to avoid re-creating and extra file reads
                    if isinstance(mat_fn, Material):
                        self.materials.append(mat_fn)
                    else:
                        self.materials.append(Material(mat_fn))
        else:
            raise Exception('Bad material variable: %s' % str(mat_filename))

        #~ if self.check_overlap():
            #~ print('Warning: Spheres are overlapping!')

    def _set_material(self, mat_filename):
        if isinstance(mat_filename, Material):
            mat = mat_filename
        else:
            mat = Material(mat_filename)
        self.materials = [mat for i in xrange(self.N)]

    def load(self, filename, mat_filename='etaGold.txt', units='nm'):
        """
            Reads spheres coordinates and radii from file.
            Material of all spheres currently is set to mat_filename.
            if units are 'mum' then spheres are scaled to nm (x1000).
        """
        x = []
        y = []
        z = []
        a = []
        try:
            f = open(filename, 'r')
            text = f.readlines()
            for line in text:
                words = [w.strip() for w in line.replace(',', '.').split()]
                data  = [float(w) for w in words]
                a.append(data[0])
                x.append(data[1])
                y.append(data[2])
                z.append(data[3])
            f.close()
        except Exception as err:
            print('Load failed \n %s' % err)
        self.N = len(a)
        self.x = np.array(x)
        self.y = np.array(y)
        self.z = np.array(z)
        self.a = np.array(a)
        if units == 'mum':
            self.x = self.x * 1000.0
            self.y = self.y * 1000.0
            self.z = self.z * 1000.0
            self.a = self.a * 1000.0
        self._set_material(mat_filename)


class Background(object):
    """
    Base class for calculating background. Constant background is implemented.
    Other backgrounds should inherit from this.
    """
    def __init__(self, wavelengths):
        self.wavelengths = wavelengths

    def _check(self, params):
        if len(params) < self.number_of_params():
            raise Exception('Not enought parameters in params array! '+str(params))

    def number_of_params(self):
        return 1

    def get_bkg(self, params):
        self._check(params)
        return params[0]

    def plot(self, params, fig=None, axs=None):
        """
        plot background
        params : list of parameters
        fig, axs : matplotlib objects
        """
        flag = fig is None
        if flag:
            fig = plt.figure()
            axs = fig.add_subplot(111)
        x = self.wavelengths
        y = self.get_bkg(params)
        if isinstance(y, float):  # if not an array
            y = y * np.ones(len(x))
        axs.plot(x, y, 'g--', label='Bkg')
        axs.set_ylabel('Intensity')
        axs.set_xlabel('Wavelength, nm')
        axs.legend()
        if flag:
            plt.show()


class LinearBackground (Background):
    """
        Background function a * x + b
    """
    def number_of_params(self):
        return 2

    def get_bkg(self, params):
        self._check(params)
        return params[0] + params[1] * self.wavelengths


class LorentzBackground (Background):
    """
        Background Lorentz function
    """
    def number_of_params(self):
        return 3

    def get_bkg(self, params, vklad_UV=250):
        self._check(params)
        return params[0] + params[1] / ((self.wavelengths-vklad_UV)**2 + (params[2])**2)


class FilmBackground (Background):
    """
        Background interpolated from experimental spectra of gold foil
    """
    def number_of_params(self):
        return 3

    def get_bkg(self, params):
        self._check(params)
        return params[0] + params[1] * gold_film_ex(params[2], self.wavelengths)


if __name__== '__main__':
    print ('Overlap tests')
    spheres = Spheres()
    print('  Test not overlapped... ')
    spheres.x = [-5, 5]
    spheres.y = [ 0, 0]
    spheres.z = [ 0, 0]
    spheres.a = [ 4, 4]
    assert(not spheres.check_overlap())
    print('  Test overlapped... ')
    spheres.a = [ 5, 5]
    assert(spheres.check_overlap())
    print('  Test nested... ')
    spheres.x = [ 0, 0]
    spheres.a = [ 2, 5]
    assert(not spheres.check_overlap())
    spheres.a = [ 5, 3]
    assert(not spheres.check_overlap())
    raw_input('Press enter')

    print ('Materials test')
    mat  = Material('etaGold.txt')
    mat.plot()
    mat1 = Material('etaSilver.txt')
    mat2 = Material('etaGold_analyt.txt')
    mat3 = Material('glass')
    mat4 = Material('etaWater.txt')
    mat5 = Material(1.5)
    mat6 = Material('2.0+0.5j')
    print 'etaGold ', mat.get_n(800)
    print 'etaSilver ', mat1.get_n(800)
    print 'etaGold analyt ', mat2.get_n(500)
    print 'Glass (constant) ', mat3.get_n(800), mat3.get_k(800)
    print 'etaWater  ', mat4.get_n(800)
    print 'n=1.5 material ', mat5.get_n(550)
    print 'n=2.0+0.5j material ', mat6.get_n(550), mat6.get_k(550)
    raw_input('Press enter')
    with Profiler() as p:
        wls = np.linspace(300, 800, 100)
        # create SPR object
        spr = SPR(wls)
        spr.environment_material = 'air'
        spr.set_spheres(SingleSphere(0.0, 0.0, 0.0, 25.0, 'etaGold.txt'))
        # spr.set_spheres(LogNormalSpheres(27, 0.020, 0.9, 0.050 ))
        # calculate!
        spr.simulate('extinction.txt')
    spr.plot()
    raw_input('Press enter')
