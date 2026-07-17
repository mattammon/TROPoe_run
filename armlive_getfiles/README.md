# Python scripts for ARMLIVE Web service
A collection of python packages to assist using armlive web service

## Installation

### Pip install
This collection is a pip installable project that will install it's own dependencies. 
The only requirement for using it is having pip installed on the user local machine. 
With pip installed run the following command to install this package into the python 
path for the uer local machine. 
```
pip install git+https://code.ornl.gov/ofg/armlive_getfiles.git
```
Once pip installs the package the following command can be run on the command line for more info.
```
getARMFiles --help
```

### Clone install
Alternatively, the repository can be cloned and run using python if the requests package is installed.
Clone the project and navigate to the src directory and run the following command for more info.
```python getFiles.py --help```

### Disclaimer
This script will have issues verifying ssl certificates when using a mac and a proxy connection. To insure 
that it will work in the most situations ssl cert verification has been disabled. Please use at your own risk.  

### Need help with pip?
<details><summary>Click Here</summary>

### What Is PIP for Python?
PIP is a recursive acronym that stands for “PIP Installs Packages” or “Preferred Installer Program”. It’s a command-line utility that allows you to install, reinstall, or uninstall PyPI packages with a simple and straightforward command: pip.

If you’ve ever done any command-line work on Windows (with the Command Prompt) or Mac or Linux (with the Terminal and Bash), then you’ll feel right at home and can skip down to the installation instructions for your particular operating system.

### Is PIP Installed With Python?
If you’re using Python 2.7.9 (or greater) or Python 3.4 (or greater), then PIP comes installed with Python by default. If you’re using an older version of Python, you’ll need to use the installation steps below. Otherwise, skip to the bottom to learn how to start using PIP.

If you’re running Python in a virtual environment created with either virtualenv or pyvenv, then PIP will be available to that environment regardless of Python version. Learn more about Python virtual environments and why they’re useful.

### Is Python Correctly Installed?
You have to make sure Python is properly installed on your system. On Windows, open up the Command Prompt using Windows key + X and selecting Command Prompt. On Mac, open the Terminal using Command + Space and searching for terminal. On Linux, open the Terminal using Ctrl + Alt + T or however else it’s done in your particular distro.

Then type:

python --version
On Linux, Python 3.x users may need to use:

python3 --version
If you get a version number (e.g. “Python 2.7.5”), then it means Python is ready to go.

If you get a “Python is not defined” message, then you’ll have to first install Python properly. That’s beyond the scope of this article. Visit the Python site for instructions.

### How to Install PIP on Windows
The following instructions should work on Windows 7, Windows 8.1, and Windows 10:

Download the get-pip.py installer script. If you’re on Python 3.2, you’ll need this version of get-pip.py instead. Either way, right-click on the link and select Save As… and save it to any safe location, such as your Downloads folder.
Open the Command Prompt and navigate to the get-pip.py file.
Run the following command: python get-pip.py

### How to Install PIP on Mac
Modern Mac systems come with Python and PIP already installed. However, this version of Python tends to be outdated and not the best choice for serious Python development, so it’s highly recommended that you install a more current version of Python and PIP.

If you want to use the native system Python installation but don’t have PIP available, you can install PIP with the following command in Terminal:

sudo easy_install pip
If you’d rather install a more up-to-date version of Python, then you can use Homebrew. Don’t know what that is? Learn more about installing software with Homebrew on Mac. The following instructions assume you already have Homebrew installed and ready to go.

#### Installing Python with Homebrew involves a single command:

brew install python
This will install the latest version of Python, which should come packaged with PIP. If the installation is successful but PIP is unavailable, you may need to re-link Python using the following Terminal command:

brew unlink python && brew link python

### How to Install PIP on Linux
If your Linux distro came with Python already installed, you should be able to install PIP using your system’s package manager. This is preferable since system-installed versions of Python do not play nicely with the get-pip.py script used on Windows and Mac.

Advanced Package Tool (Python 2.x)

sudo apt-get install python-pip
Advanced Package Tool (Python 3.x)

sudo apt-get install python3-pip
pacman Package Manager (Python 2.x)

sudo pacman -S python2-pip
pacman Package Manager (Python 3.x)

sudo pacman -S python-pip
Yum Package Manager (Python 2.x)

sudo yum upgrade python-setuptools
sudo yum install python-pip python-wheel
Yum Package Manager (Python 3.x)

sudo yum install python3 python3-wheel
Dandified Yum (Python 2.x)

sudo dnf upgrade python-setuptools
sudo dnf install python-pip python-wheel
Dandified Yum (Python 3.x)

sudo dnf install python3 python3-wheel
Zypper Package Manager (Python 2.x)

sudo zypper install python-pip python-setuptools python-wheel
Zypper Package Manager (Python 3.x)

sudo zypper install python3-pip python3-setuptools python3-wheel

### How to Install PIP on Raspberry Pi
As a Raspberry Pi user, you’re probably running Raspbian since it’s the official operating system designated and provided by the Raspberry Pi Foundation. You’re free to install another operating system, such as Ubuntu, but in that case you should look at the Linux instructions.

Starting with Raspbian Jessie, PIP comes installed by default. It’s one of the big reasons to upgrade to Raspbian Jessie instead of sticking with Raspbian Wheezy or Raspbian Jessie Lite. However, if you’re on an older version of Raspbian, you can still install PIP.

#### On Python 2.x:

sudo apt-get install python-pip
#### On Python 3.x:

sudo apt-get install python3-pip
With Raspbian, Python 2.x users should use pip while Python 3.x users should use pip3 when issuing PIP commands.

### How to Upgrade PIP for Python
While PIP itself doesn’t update very often, it’s still important to stay on top of new versions because there may be important fixes to bugs, compatibility, and security holes. Fortunately, upgrading PIP is very fast and simple.

#### On Windows:

python -m pip install -U pip
#### On Mac, Linux, or Raspberry Pi:

pip install -U pip
On certain versions of Linux and Raspberry Pi, you may need to use pip3 instead.

### How to Manage Python Packages With PIP
Once PIP is ready, you can start installing packages from PyPI:

pip install package-name
To install a specific version of a package instead of the latest version:

pip install package-name==1.0.0
To search PyPI for a particular package:

pip search "query"
To see details about an installed package:

pip show package-name
To list all installed packages:

pip list
To list all outdated packages:

pip list --outdated
To upgrade an outdated package:

pip install package-name --upgrade
Note that older versions of a package are automatically removed by PIP when upgrading to a newer version of that package.

To completely reinstall a package:

pip install package-name --upgrade --force-reinstall
To completely get rid of a package:

pip uninstall package-name
</details>
