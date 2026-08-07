from setuptools import setup, find_packages

setup(
    name="csv-data-cleaner",
    version="0.1.0",
    description="A Python library for cleaning, validating, and standardizing CSV data.",
    author="Matt",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
    ],
)
