from setuptools import setup, find_packages

setup(
    name='armlive: get files',
    description='Auto downloader for using armlive web service from ADC',
    version='1.2.1',
    url='https://adc.arm.gov/armlive/',
    author='Michael Giansiracusa',
    author_email='giansiracumt@ornl.gov',
    packages=find_packages(),
    install_requires=[
        'requests',
        'urllib3',
    ],
    entry_points = {
            'console_scripts': [
                'getARMFiles = src.getFiles:main',
            ],
        }
)
