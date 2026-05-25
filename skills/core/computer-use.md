# Skill: Native Computer Use (Desktop Automation)

Этот навык позволяет ИИ-агенту взаимодействовать с графическим интерфейсом операционной системы: «видеть» экран, нажимать кнопки и вводить текст, как это делает настоящий человек.

## Доступные команды (`agentctl desktop`)

1. **`agentctl desktop info`**
   Возвращает разрешение экрана и ОС (например, `{"width": 2560, "height": 1440, "os": "linux"}`).

2. **`agentctl desktop shot <path>`**
   Делает скриншот всего экрана и сохраняет по указанному пути.
   *Пример:* `agentctl desktop shot /tmp/screen.png`

3. **`agentctl desktop click <x> <y> [button]`**
   Перемещает мышь на указанные координаты и делает клик (button: 1 - левый, 2 - средний, 3 - правый).
   *Пример:* `agentctl desktop click 1200 800`

4. **`agentctl desktop type "<text>"`**
   Вводит текст.
   *Пример:* `agentctl desktop type "Hello World"`

5. **`agentctl desktop key <key>`**
   Нажимает системную клавишу (например, `Return`, `Escape`, `Ctrl+C`).
   *Пример:* `agentctl desktop key Return`

## Алгоритм работы ("Зрение" + "Действие")

Поскольку ты (агент) работаешь удалённо, чтобы увидеть экран, нужно:
1. Сделать скриншот на ПК пользователя: 
   `./b.sh "agentctl desktop shot /tmp/screen.png"`
2. Скачать его в свой воркспейс:
   `./download.sh /tmp/screen.png screen.png`
3. Использовать инструменты зрения (например, `read_file` в Arena.ai) для анализа `screen.png`.
4. Найти нужные элементы, вычислить их X и Y координаты.
5. Отправить команду клика:
   `./b.sh "agentctl desktop click X Y"`

## Поддержка ОС
- **Linux (Wayland):** Работает через `ydotool` (мышь/клавиатура), `wtype`, `grim` или `spectacle` (скриншоты). Служба `ydotoold` запускается автоматически.
- **Windows:** Работает через `pyautogui` и `Pillow` (устанавливаются автоматически при первом запуске).
