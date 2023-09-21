"""Setup officer plugin."""

from setuptools import find_packages, setup

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="netbox-config-officer",
    version="0.1.1",
    description="A plugin designed to store configurations and track differences, while also ensuring compliance with templates.",
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
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    url='https://github.com/artyomovs/netbox-plugin-config-officer',
)

