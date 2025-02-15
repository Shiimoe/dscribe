import math
import pytest
import numpy as np
import scipy.constants
from numpy.random import RandomState
from ase import Atoms
from testutils import (
    get_ewald_sum_matrix_default_setup,
    get_ewald_sum_matrix_automatic_setup,
    load_ewald,
)
from conftest import (
    assert_matrix_descriptor_exceptions,
    assert_matrix_descriptor_flatten,
    assert_matrix_descriptor_sorted,
    assert_matrix_descriptor_eigenspectrum,
    assert_matrix_descriptor_random,
    assert_no_system_modification,
    assert_sparse,
    assert_parallellization,
    assert_symmetries,
    assert_derivatives,
    big_system,
    water,
)
from dscribe.descriptors import EwaldSumMatrix

r_cut = 30
g_cut = 20


# =============================================================================
# Utilities
def ewald_sum_matrix(**kwargs):
    def func(systems=None):
        n_atoms_max = None if systems is None else max([len(s) for s in systems])
        final_kwargs = {
            "n_atoms_max": n_atoms_max,
            "permutation": "none",
            "flatten": True,
        }
        final_kwargs.update(kwargs)
        if (
            final_kwargs["permutation"] == "random"
            and final_kwargs.get("sigma") is None
        ):
            final_kwargs["sigma"] = 2
        return EwaldSumMatrix(**final_kwargs)

    return func


# =============================================================================
# Common tests with parametrizations that may be specific to this descriptor
def test_matrix_descriptor_exceptions():
    assert_matrix_descriptor_exceptions(ewald_sum_matrix)


def test_matrix_descriptor_flatten():
    assert_matrix_descriptor_flatten(ewald_sum_matrix)


def test_matrix_descriptor_sorted():
    assert_matrix_descriptor_sorted(ewald_sum_matrix)


def test_matrix_descriptor_eigenspectrum():
    assert_matrix_descriptor_eigenspectrum(ewald_sum_matrix)


def test_matrix_descriptor_random():
    assert_matrix_descriptor_random(ewald_sum_matrix)


@pytest.mark.parametrize(
    "n_jobs, flatten, sparse",
    [
        (1, True, False),  # Serial job, flattened, dense
        (2, True, False),  # Parallel job, flattened, dense
        (2, False, False),  # Unflattened output, dense
        (1, True, True),  # Serial job, flattened, sparse
        (2, True, True),  # Parallel job, flattened, sparse
        (2, False, True),  # Unflattened output, sparse
    ],
)
def test_parallellization(n_jobs, flatten, sparse):
    assert_parallellization(ewald_sum_matrix, n_jobs, flatten, sparse)


def test_no_system_modification():
    assert_no_system_modification(ewald_sum_matrix)


def test_sparse():
    assert_sparse(ewald_sum_matrix)


@pytest.mark.parametrize(
    "permutation_option, translation, rotation, permutation",
    [
        ("none", True, True, False),
        ("eigenspectrum", True, True, True),
        ("sorted_l2", False, False, False),
    ],
)
def test_symmetries(permutation_option, translation, rotation, permutation):
    """Tests the symmetries of the descriptor. Notice that sorted_l2 is not
    guaranteed to have any of the symmetries due to numerical issues with rows
    that have nearly equal norm."""
    assert_symmetries(
        ewald_sum_matrix(permutation=permutation_option),
        translation,
        rotation,
        permutation,
    )


# =============================================================================
# Tests that are specific to this descriptor.
@pytest.mark.parametrize(
    "permutation, n_features",
    [
        ("none", 25),
        ("eigenspectrum", 5),
        ("sorted_l2", 25),
    ],
)
def test_number_of_features(permutation, n_features):
    """Tests that the reported number of features is correct."""
    desc = EwaldSumMatrix(n_atoms_max=5, permutation="none", flatten=False)
    n_features = desc.get_number_of_features()
    assert n_features == 25


def test_create():
    """Tests different valid and invalid create values."""
    system = water()
    with pytest.raises(ValueError):
        desc = EwaldSumMatrix(n_atoms_max=5)
        desc.create(system, r_cut=10)
    with pytest.raises(ValueError):
        desc = EwaldSumMatrix(n_atoms_max=5)
        desc.create(system, g_cut=10)

    # Providing a only is valid
    desc = EwaldSumMatrix(n_atoms_max=5)
    desc.create(system, a=0.5)

    # Providing no parameters is valid
    desc = EwaldSumMatrix(n_atoms_max=5)
    desc.create(system)


def test_a_independence():
    """Tests that the matrix elements are independent of the screening
    parameter 'a' used in the Ewald summation. Notice that the real space
    cutoff and reciprocal space cutoff have to be sufficiently large for
    this to be true, as 'a' controls the width of the Gaussian charge
    distribution.
    """
    r_cut = 40
    g_cut = 30
    system = water()
    prev_array = None
    for i, a in enumerate([0.1, 0.5, 1, 2, 3]):
        desc = EwaldSumMatrix(n_atoms_max=5, permutation="none", flatten=False)
        matrix = desc.create(system, a=a, r_cut=r_cut, g_cut=g_cut)

        if i > 0:
            assert np.allclose(prev_array, matrix, atol=0.001, rtol=0)
        prev_array = matrix


@pytest.mark.parametrize(
    "setup",
    [
        (get_ewald_sum_matrix_default_setup),
        (get_ewald_sum_matrix_automatic_setup),
    ],
)
def test_electrostatics(setup):
    """Tests that the results are consistent with the electrostatic
    interpretation. Each matrix [i, j] element should correspond to the
    Coulomb energy of a system consisting of the pair of atoms i, j.
    """
    system, desc_args, create_args = setup()
    desc = EwaldSumMatrix(**desc_args)
    n_atoms = len(system)

    # The Ewald matrix contains the electrostatic interaction between atoms
    # i and j. Here we construct the total electrostatic energy for a
    # system consisting of atoms i and j.
    matrix = desc.create(system, **create_args)
    energy_matrix = np.zeros(matrix.shape)
    for i in range(n_atoms):
        for j in range(n_atoms):
            if i == j:
                energy_matrix[i, j] = matrix[i, j]
            else:
                energy_matrix[i, j] = matrix[i, j] + matrix[i, i] + matrix[j, j]

    # Converts unit of q*q/r into eV
    conversion = 1e10 * scipy.constants.e / (4 * math.pi * scipy.constants.epsilon_0)
    energy_matrix *= conversion

    # The value in each matrix element should correspond to the Coulomb
    # energy of a system with with only those atoms. Here the energies from
    # the Ewald matrix are compared against the Ewald energy calculated
    # with pymatgen.
    energy_pymatgen = load_ewald(create_args)
    assert np.allclose(energy_matrix, energy_pymatgen, atol=1e-5, rtol=0)


def test_unit_cells():
    """Tests if arbitrary unit cells are accepted"""
    desc = EwaldSumMatrix(n_atoms_max=3, permutation="none", flatten=False)
    molecule = water()

    # A system without cell should produce an error
    molecule.set_cell([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    with pytest.raises(ValueError):
        nocell = desc.create(molecule, a=0.5, r_cut=r_cut, g_cut=g_cut)

    # Large cell
    molecule.set_pbc(True)
    molecule.set_cell([[20.0, 0.0, 0.0], [0.0, 30.0, 0.0], [0.0, 0.0, 40.0]])
    largecell = desc.create(molecule, a=0.5, r_cut=r_cut, g_cut=g_cut)

    # Cubic cell
    molecule.set_cell([[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]])
    cubic_cell = desc.create(molecule, a=0.5, r_cut=r_cut, g_cut=g_cut)

    # Triclinic cell
    molecule.set_cell([[0.0, 2.0, 2.0], [2.0, 0.0, 2.0], [2.0, 2.0, 0.0]])
    triclinic_smallcell = desc.create(molecule, a=0.5, r_cut=r_cut, g_cut=g_cut)
