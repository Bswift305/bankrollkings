$ErrorActionPreference = 'Stop'
Set-Location 'C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls'
& 'C:\Users\Decatur\AppData\Local\Python\pythoncore-3.14-64\python.exe' -c "from app import app; app.run(debug=False, use_reloader=False, threaded=True, host='127.0.0.1', port=5001)"
