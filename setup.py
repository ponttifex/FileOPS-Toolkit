from setuptools import setup, find_packages

setup(
    name='fileops_toolkit',
    version='0.3.0',
    description='Modular, parallel, and intelligent file deduplication & transfer system',
    author='FileOps Toolkit Authors',
    license='MIT',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
        'click>=8.0',
        'rich>=12.0',
        'xxhash>=3.0',
        'paramiko>=3.0'
    ],
    entry_points={
        'console_scripts': [
            'fileops-toolkit=fileops_toolkit.console.main:cli',
        ],
    },
    python_requires='>=3.8',
)
