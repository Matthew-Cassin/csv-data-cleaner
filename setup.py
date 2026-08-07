from pathlib import Path

from setuptools import find_packages, setup

THIS_DIR = Path(__file__).parent
LONG_DESCRIPTION = (THIS_DIR / "README.md").read_text(encoding="utf-8")

setup(
    name="csv-data-cleaner",
    version="0.1.0",
    description=(
        "A Python library for cleaning, validating, and standardizing "
        "CSV data."
    ),
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="Matt",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    install_requires=[
        "pandas>=3.0.5,<4.0.0",
        "numpy>=2.5.1,<3.0.0",
        "chardet>=7.5.1,<8.0.0",
        "click>=8.4.2,<9.0.0",
        "tabulate>=0.10.0,<0.11.0",
        "email-phone-validator @ git+https://github.com/Matthew-Cassin/"
        "email-phone-validator.git@v0.1.0",
    ],
    entry_points={
        "console_scripts": [
            "csv-data-cleaner=csv_data_cleaner.cli:clean",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3 :: Only",
        "Environment :: Console",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Scientific/Engineering :: Information Analysis",
    ],
    keywords="csv data-cleaning data-quality validation pandas",
)
