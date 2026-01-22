@echo off
cls

echo ##########################
echo Babel translations updater
echo ##########################
echo.
echo.
echo Import of all new strings.
echo.
echo.
pybabel extract -F babel.cfg -o messages.pot .
echo.
pybabel update -i messages.pot -d translations
echo.
echo.
echo Now, translate every .po files located in translations\xx\LC_MESSAGES
echo Then come back and press a key !
echo.
pause
echo.
echo Compilation of translations
pybabel compile -d translations
echo.
echo.
echo Success 