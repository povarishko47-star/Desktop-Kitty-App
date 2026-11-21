ЯЗЫК
  Кнопка в правом верхнем углу лаунчера переключает русский и английский. При первом запуске язык выбирается по
  языку Windows (русский, иначе английский). Выбор запоминается.

ЕСЛИ АНТИВИРУС ИЛИ SMARTSCREEN РУГАЕТСЯ
  Программа не подписана цифровой подписью (она платная), поэтому Windows может написать «Неизвестный издатель».
  Нажмите «Подробнее» → «Выполнить в любом случае». Это нормально для самодельных программ.
  Если антивирус удаляет именно один файл MoyKotik.exe, соберите версию в папке (запускается быстрее и реже
  вызывает подозрения): откройте командную строку в этой папке и выполните   build_exe.bat folder
  Тогда программа будет в папке dist\MoyKotik (запускайте MoyKotik.exe внутри неё; папку можно заархивировать).

ГДЕ ЖИВУТ НАСТРОЙКИ
  Файл  %LOCALAPPDATA%\DesktopCompanion_config.json  (в адресной строке проводника вставьте это и нажмите Enter).
  Там сохранены коты, цвета, свои расцветки, снег, режим нагрузки, уведомления и язык. Удалите файл, чтобы начать с нуля.
  Удалить программу: закройте её через значок в трее («Полный выход») и удалите exe и этот файл.

АВТОЗАПУСК ПРИ ВКЛЮЧЕНИИ WINDOWS (по желанию, без кода)
  1. Нажмите Win+R, введите   shell:startup   и Enter: откроется папка автозагрузки.
  2. Правой кнопкой по MoyKotik.exe → «Создать ярлык», перетащите ярлык в эту папку.
  Чтобы убрать автозапуск, удалите ярлык из той же папки.


## LANGUAGE

The button in the top-right corner of the launcher switches between Russian and English.

On the first launch, the language is selected automatically based on your Windows language (Russian if Windows is set to Russian, English otherwise). Your selection is saved and remembered for future launches.

## IF YOUR ANTIVIRUS OR WINDOWS SMARTSCREEN SHOWS A WARNING

The application is not digitally signed (code-signing certificates are paid), so Windows may display an "Unknown publisher" warning.

Click **More info → Run anyway**. This is normal for independently developed software.

If your antivirus deletes `MoyKotik.exe` specifically, try building the folder version instead (it launches faster and is less likely to trigger false positives):

1. Open Command Prompt in the project folder.
2. Run:

   ```cmd
   build_exe.bat folder
   ```

3. The application will be built in `dist\MoyKotik`.

Run `MoyKotik.exe` from inside that folder. You can also compress the entire folder into a ZIP archive for distribution.

## WHERE YOUR SETTINGS ARE STORED

All settings are stored in:

```text
%LOCALAPPDATA%\DesktopCompanion_config.json
```

To open it, paste the path into the File Explorer address bar and press Enter.

This file stores:
- Selected cats
- Colors and custom color schemes
- Snow settings
- Performance mode
- Notifications
- Language preference

Delete this file to reset the application to its default settings.

**To uninstall the application:**

1. Close it using the system tray icon → **Full Exit**.
2. Delete the application `.exe` file (or its entire folder).
3. Delete the configuration file mentioned above.

## START AUTOMATICALLY WITH WINDOWS (OPTIONAL, NO CODING REQUIRED)

1. Press `Win + R`, type `shell:startup`, and press Enter. This opens the Windows Startup folder.
2. Right-click `MoyKotik.exe` and select **Create shortcut**.
3. Move the newly created shortcut into the Startup folder.

To disable automatic startup, simply delete the shortcut from that folder.
