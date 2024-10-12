# kontakt-library-adder
A simple Python script to manually add Kontakt libraries, without the need to use Native Access.

For simplified usage, you can either run `python add-library.py [gui]` from the command-line, or run the `run.bat` script. The `run.bat` script will also ensure all dependencies are installed through pip.

Before running the script, make sure you have Python 3 installed, alongside the required dependencies:
```
pip install -r requirements.txt
```

Example usage:
```
> python add-library.py "E:\Kontakt Libraries\Straight Ahead Samples - Atomic Big Band The Horns"

[.] Library information:
[.]    Name: Atomic Big Band! The Horns
[.]    Company: Straight Ahead Samples
[.]    Registry key: Atomic Big Band! The Horns
[.]    Version: 1.0.0

[+] Library added!
```