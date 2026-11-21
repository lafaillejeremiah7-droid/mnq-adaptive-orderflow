"""Build the optional C++20 research kernel: python setup.py build_ext --inplace."""
from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension, build_ext

setup(
    name="mnq-research-native-acceleration",
    version="0.1.0",
    description="Optional C++ batch kernel for offline NQ/MNQ research",
    ext_modules=[
        Pybind11Extension(
            "company._nq_cpp",
            ["company/_nq_cpp.cpp"],
            cxx_std=20,
            extra_compile_args=["-O3"],
        )
    ],
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
)
