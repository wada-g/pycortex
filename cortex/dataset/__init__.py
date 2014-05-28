"""Module for maintaining brain data and their masks

Three basic classes, with child classes:
  1. Dataset
  2. BrainData
    a. VolumeData
    b. VertexData
  3. View
    a. DataView

Dataset holds a collection of View and BrainData objects. It provides a thin
wrapper around h5py to store data. Datasets will store all View and BrainData
objects into the h5py file, reconstituting each when requested.


"""

import tempfile
import numpy as np
import h5py

from ..database import db
from ..xfm import Transform

from .braindata import BrainData, VertexData, VolumeData, _hdf_write
from .views import View, Volume, Vertex, RGBVolume, RGBVertex

class Dataset(object):
    def __init__(self, **kwargs):
        self.h5 = None
        self.views = {}

        self.append(**kwargs)

    def append(self, **kwargs):
        for name, data in kwargs.items():
            norm = normalize(data)

            if isinstance(norm, View):
                self.views[name] = norm
            elif isinstance(norm, BrainData):
                self.views[name] = DataView(norm)
            elif isinstance(norm, Dataset):
                self.views.update(norm.views)

        return self

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        elif attr in self.views:
            return self.views[attr]

        import ipdb
        ipdb.set_trace()

        raise AttributeError

    def __getitem__(self, item):
        return self.views[item]

    def __iter__(self):
        for name, dv in sorted(self.views.items(), key=lambda x: x[1].priority):
            yield name, dv

    def __repr__(self):
        views = sorted(self.views.items(), key=lambda x: x[1].priority)
        return "<Dataset with views [%s]>"%(', '.join([n for n, d in views]))

    def __len__(self):
        return len(self.views)

    def __dir__(self):
        return list(self.__dict__.keys()) + list(self.views.keys())

    @classmethod
    def from_file(cls, filename):
        ds = cls()
        ds.h5 = h5py.File(filename)
        loaded = set()

        db.auxfile = ds

        #detect stray datasets which were not written by pycortex
        for name, node in ds.h5.items():
            if name in ("data", "subjects", "views"):
                continue
            try:
                ds.views[name] = DataView(BrainData.from_hdf(ds, node))
            except KeyError:
                print('No metadata found for "%s", skipping...'%name)

        #load up the views generated by pycortex
        for name, node in ds.h5['views'].items():
            ds.views[name] = DataView.from_hdf(ds, node)
            for bd in ds.views[name]:
                loaded.add(bd.name)

        #catch any data objects that have no corresponding view
        for name, node in ds.h5['data'].items():
            if name not in loaded:
                try:
                    ds.views[name] = DataView(BrainData.from_hdf(ds, node))
                except KeyError:
                    print('No metadata found for "%s", skipping...'%name)

        db.auxfile = None

        return ds
        
    def uniques(self):
        """Return the set of unique BrainData objects contained by this dataset"""
        uniques = set()
        for name, view in self:
            for data in view:
                uniques.add(data)

        return uniques

    def save(self, filename=None, pack=False):
        if filename is not None:
            self.h5 = h5py.File(filename)
        elif self.h5 is None:
            raise ValueError("Must provide filename for new datasets")

        for name, view in self.views.items():
            view._write_hdf(self.h5, name=name)

        if pack:
            subjs = set()
            xfms = set()
            masks = set()
            for view in self.views.values():
                for data in view:
                    subjs.add(data.subject)
                    xfms.add((data.subject, data.xfmname))
                    #custom masks are already packaged by default
                    #only string masks need to be packed
                    if isinstance(data._mask, str):
                        masks.add((data.subject, data.xfmname, data._mask))
            _pack_subjs(self.h5, subjs)
            _pack_xfms(self.h5, xfms)
            _pack_masks(self.h5, masks)

        self.h5.flush()

    def get_surf(self, subject, type, hemi='both', merge=False, nudge=False):
        if hemi == 'both':
            left = self.get_surf(subject, type, "lh", nudge=nudge)
            right = self.get_surf(subject, type, "rh", nudge=nudge)
            if merge:
                pts = np.vstack([left[0], right[0]])
                polys = np.vstack([left[1], right[1]+len(left[0])])
                return pts, polys

            return left, right
        try:
            if type == 'fiducial':
                wpts, polys = self.get_surf(subject, 'wm', hemi)
                ppts, _     = self.get_surf(subject, 'pia', hemi)
                return (wpts + ppts) / 2, polys

            group = self.h5['subjects'][subject]['surfaces'][type][hemi]
            pts, polys = group['pts'].value.copy(), group['polys'].value.copy()
            if nudge:
                if hemi == 'lh':
                    pts[:,0] -= pts[:,0].max()
                else:
                    pts[:,0] -= pts[:,0].min()
            return pts, polys
        except (KeyError, TypeError):
            raise IOError('Subject not found in package')

    def get_xfm(self, subject, xfmname):
        try:
            group = self.h5['subjects'][subject]['transforms'][xfmname]
            return Transform(group['xfm'].value, tuple(group['xfm'].attrs['shape']))
        except (KeyError, TypeError):
            raise IOError('Transform not found in package')

    def get_mask(self, subject, xfmname, maskname):
        try:
            group = self.h5['subjects'][subject]['transforms'][xfmname]['masks']
            return group[maskname]
        except (KeyError, TypeError):
            raise IOError('Mask not found in package')

    def get_overlay(self, subject, type='rois', **kwargs):
        try:
            group = self.h5['subjects'][subject]
            if type == "rois":
                tf = tempfile.NamedTemporaryFile()
                tf.write(group['rois'][0])
                tf.seek(0)
                return tf
        except (KeyError, TypeError):
            raise IOError('Overlay not found in package')

        raise TypeError('Unknown overlay type')

    def prepend(self, prefix):
        ds = dict()
        for name, data in self:
            ds[prefix+name] = data

        return Dataset(**ds)

def normalize(data):
    if isinstance(data, (Dataset, View)):
        return data
    elif isinstance(data, BrainData):
        return DataView(data)
    elif isinstance(data, dict):
        return Dataset(**data)
    elif isinstance(data, str):
        return Dataset.from_file(data)
    elif isinstance(data, tuple):
        if len(data) == 3:
            return DataView(VolumeData(*data))
        else:
            return DataView(VertexData(*data))
    elif isinstance(data, list):
        return DataView(data)

    raise TypeError('Unknown input type')

def _pack_subjs(h5, subjects):
    for subject in subjects:
        rois = db.get_overlay(subject, type='rois')
        rnode = h5.require_dataset("/subjects/%s/rois"%subject, (1,),
            dtype=h5py.special_dtype(vlen=str))
        rnode[0] = rois.toxml(pretty=False)

        surfaces = db.get_paths(subject)['surfs']
        for surf in surfaces.keys():
            for hemi in ("lh", "rh"):
                pts, polys = db.get_surf(subject, surf, hemi)
                group = "/subjects/%s/surfaces/%s/%s"%(subject, surf, hemi)
                _hdf_write(h5, pts, "pts", group)
                _hdf_write(h5, polys, "polys", group)

def _pack_xfms(h5, xfms):
    for subj, xfmname in xfms:
        xfm = db.get_xfm(subj, xfmname, 'coord')
        group = "/subjects/%s/transforms/%s"%(subj, xfmname)
        node = _hdf_write(h5, np.array(xfm.xfm), "xfm", group)
        node.attrs['shape'] = xfm.shape

def _pack_masks(h5, masks):
    for subj, xfm, maskname in masks:
        mask = db.get_mask(subj, xfm, maskname)
        group = "/subjects/%s/transforms/%s/masks"%(subj, xfm)
        _hdf_write(h5, mask, maskname, group)
