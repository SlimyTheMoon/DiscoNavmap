Data updates are fully automated now:
1. python -m cmd_py.update -out data/vX   (imports game data, extracts infocards from DLLs)
2. python build.py                         (builds the static site into docs/)

The tools in this folder are only needed for updating planet/system textures:
1. get planet textures using UTF Image Exporter (utils/UTFImageExporter)
2. batch convert from txm to jpg using IrfanView recursively
3. rename files to ##.jpg where the number ## is a file counter for each
   sub-directory using Metamorphose2 (installer in this folder) - the navmap
   expects a file named 01.jpg inside each txm folder
4. lowercase everything