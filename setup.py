"""Setup officer plugin."""

from setuptools import find_packages, setup

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="netbox-plugin-config-officer",
    version="0.0.1",
    description="NetBox plugin that store configuration/diffs, and check compliance with templates",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Sergei Artemov",
    author_email='artemov.sergey1989@gmail.com',
    license="Apache 2.0",
    install_requires=[
        'diffios',
        'scrapli',
        'GitPython',
        'PyDriller==1.15.3',
        'xlsxwriter',
    ],
    packages=find_packages(exclude=("tests",)),
    include_package_data=True,
    zip_safe=False,
    url='https://github.com/artyomovs/netbox-plugin-config-officer',
)
