from setuptools import setup

setup(name='pagerdutystats',
      version='0.0.1',
      description='Tool for calculating pager duty stats',
      url='http://github.com/livefyre/pagerdutystats',
      author='Nicholas Fowler',
      author_email='nfowler@livefyre.com',
      license='MIT',
      packages=['pagerdutystats'],
      install_requires = ['docopt', 'pygerduty', 'python-dateutil'],
      entry_points = {
        'console_scripts': [
          'pagerdutystats = pagerdutystats:main',
          ],
      },
      zip_safe=False)
