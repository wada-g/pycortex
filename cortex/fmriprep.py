from . import database
import os.path as op
import shutil
from .freesurfer import parse_curv
import numpy as np
import json
import nibabel as nib

def import_subj(subject,
                source_dir,
                session=None,
                dataset=None,
                sname=None,
                old_fmriprep=False):
    """Imports a subject from fmriprep-output.
    See https://fmriprep.readthedocs.io/en/stable/
    
    Parameters
    ----------
    subject : string
        Fmriprep subject name (without "sub-")
    source_dir : string
       Local directory that contains both fmriprep and freesurfer subfolders 
    session : string, optional
       BIDS session that contains the anatomical data (leave to default if
       not a specific session)
    dataset : string, optional
       If you have multiple fmriprep outputs from different datasets, use this attribute
       to add a prefix to every subject id ('ds01.01' rather than '01')
    sname : string, optional
        Pycortex subject name (These variable names should be changed). By default uses
        the same name as the freesurfer subject.
    old_fmriprep : boolean, optional
        Fmriprep < 1.2.0 used a different naming scheme from more recent releases.
        Flip this switch when you're using an older version of fmriprep
       """
    if sname is None:
        sname = subject

    if dataset:
        sname = '{}.{}'.format(dataset, sname)

    database.db.make_subj(sname)

    surfs = op.join(database.default_filestore, sname, "surfaces", "{name}_{hemi}.gii")
    anats = op.join(database.default_filestore, sname, "anatomicals", "{name}.nii.gz")
    surfinfo = op.join(database.default_filestore, sname, "surface-info", "{name}.npz")

    fmriprep_dir = op.join(source_dir, 'fmriprep')
    if session is not None:
        fmriprep_dir = op.join(fmriprep_dir, 'ses-{session}')
        session_str = '_ses-{session}'.format(session=session)
    else:
        session_str = ''

    # import anatomical data
    fmriprep_dir = op.join(fmriprep_dir, 'sub-{subject}', 'anat')

    if old_fmriprep:
        t1w = op.join(fmriprep_dir, 'sub-{subject}{session_str}_T1w_preproc.nii.gz')
        aseg = op.join(fmriprep_dir, 'sub-{subject}{session_str}_T1w_label-aseg_roi.nii.gz')
    else:
        t1w = op.join(fmriprep_dir, 'sub-{subject}{session_str}_desc-preproc_T1w.nii.gz')
        aseg = op.join(fmriprep_dir, 'sub-{subject}{session_str}_desc-aseg_dseg.nii.gz')

    for fmp_fn, out_fn in zip([t1w.format(subject=subject, session_str=session_str),
                               aseg.format(subject=subject, session_str=session_str)],
                              [anats.format(name='raw'),
                               anats.format(name='aseg')]):
        shutil.copy(fmp_fn, out_fn)

    
    #import surfaces
    if old_fmriprep:
        fmpsurf = op.join(fmriprep_dir, 
                          'sub-{subject}{session_str}_T1w_').format(subject=subject,
                                                                    session_str=session_str)
        fmpsurf = fmpsurf + '{fmpname}.{fmphemi}.surf.gii'
    else:
        fmpsurf = op.join(fmriprep_dir, 
                          'sub-{subject}{session_str}_').format(subject=subject,
                                                                    session_str=session_str)
        fmpsurf = fmpsurf + 'hemi-{fmphemi}_{fmpname}.surf.gii'

    for fmpname, name in zip(['smoothwm', 'pial', 'midthickness', 'inflated'],
                             ['wm', 'pia', 'fiducial', 'inflated']):
        for fmphemi, hemi in zip(['L', 'R'],
                                 ['lh', 'rh']):
            source = fmpsurf.format(fmpname=fmpname,
                                    fmphemi=fmphemi)

            target = str(surfs.format(subj=sname, name=name, hemi=hemi))

            shutil.copy(source, target)

    #import surfinfo
    curvs = op.join(source_dir,
                         'freesurfer',
                         'sub-{subject}',
                         'surf',
                         '{hemi}.{info}')

    for curv, info in dict(sulc="sulcaldepth", thickness="thickness", curv="curvature").items():
        lh, rh = [parse_curv(curvs.format(hemi=hemi, info=curv, subject=subject)) for hemi in ['lh', 'rh']]
        np.savez(surfinfo.format(subj=sname, name=info), left=-lh, right=-rh)

    database.db = database.Database()

def import_subj_no_fs(subject,
                source_dir,
                session=None,
                dataset=None,
                sname=None):
    """Imports a subject from fmriprep-output.
    See https://fmriprep.readthedocs.io/en/stable/
    
    Parameters
    ----------
    subject : string
        Fmriprep subject name (without "sub-")
    source_dir : string
        Local fmriprep bids directory
    session : string, optional
        BIDS session that contains the anatomical data (leave to default if
        not a specific session)
    dataset : string, optional
        If you have multiple fmriprep outputs from different datasets, use this attribute
        to add a prefix to every subject id ('ds01.01' rather than '01')
    sname : string, optional
        Pycortex subject name (These variable names should be changed). By default uses
        the same name as the freesurfer subject.
    """
    desc = op.join(source_dir, "dataset_description.json")
    if not op.isfile(desc):
        print("Source directory doens't contain dataset_description.json")
        return
    with open(desc, 'r') as f:
        data = json.load(f)
        # not a robust way of comparing version number, but should be enough for fmriprep
        version = float('.'.join(data["GeneratedBy"][0]["Version"].split('.')[:2]))
        # also the this is not the earliest version that can work,
        # but fmriprep doesn't document the inclusion of surf infos earlier
        # maybe it always included such files ?
        if version < 23.1:
            print(version)
            print("Version of fmriprep used requires legacy method to import subject, refer to fmriprep.import_subj")
            return
        

    if sname is None:
        sname = subject

    if dataset:
        sname = '{}.{}'.format(dataset, sname)

    database.db.make_subj(sname)

    surfs = op.join(database.default_filestore, sname, "surfaces", "{name}_{hemi}.gii")
    anats = op.join(database.default_filestore, sname, "anatomicals", "{name}.nii.gz")
    surfinfo = op.join(database.default_filestore, sname, "surface-info", "{name}.npz")

    fmriprep_dir = source_dir
    if session is not None:
        fmriprep_dir = op.join(fmriprep_dir, 'ses-{session}')
        session_str = '_ses-{session}'.format(session=session)
    else:
        session_str = ''

    # import anatomical data
    fmriprep_dir = op.join(fmriprep_dir, 'sub-{subject}', 'anat')

    t1w = op.join(fmriprep_dir, 'sub-{subject}{session_str}_desc-preproc_T1w.nii.gz')
    aseg = op.join(fmriprep_dir, 'sub-{subject}{session_str}_desc-aseg_dseg.nii.gz')

    for fmp_fn, out_fn in zip([t1w.format(subject=subject, session_str=session_str),
                               aseg.format(subject=subject, session_str=session_str)],
                              [anats.format(name='raw'),
                               anats.format(name='aseg')]):
        shutil.copy(fmp_fn, out_fn)

    
    #import surfaces
    fmpsurf = op.join(fmriprep_dir, 
                      'sub-{subject}{session_str}_').format(subject=subject,
                                                                session_str=session_str)
    fmpsurf = fmpsurf + 'hemi-{fmphemi}_{fmpname}.surf.gii'

    for fmpname, name in zip(['white', 'pial', 'midthickness', 'inflated'],
                             ['wm', 'pia', 'fiducial', 'inflated']):
        for fmphemi, hemi in zip(['L', 'R'],
                                 ['lh', 'rh']):
            source = fmpsurf.format(fmpname=fmpname,
                                    fmphemi=fmphemi)

            target = str(surfs.format(subj=sname, name=name, hemi=hemi))

            shutil.copy(source, target)

    #import surfinfo
    curvs = op.join(fmriprep_dir, 'sub-{subject}_hemi-{hemi}_{info}.shape.gii')

    for curv, info in dict(sulc="sulcaldepth", thickness="thickness", curv="curvature").items():
        lh, rh = [
                nib.load(curvs.format(hemi=hemi, info=curv, subject=subject)).darrays[0].data
                for hemi in ['L', 'R']]
        np.savez(surfinfo.format(subj=sname, name=info), left=-lh, right=-rh)

    database.db = database.Database()
