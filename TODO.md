Go through MD files in /home/priyan/uno-q-emulator. I want you help me in completing my third exercise which is gesture detection using movement detection sensor bridged to Arduino Q board. To emulate the movement detection senor, I propose the usage of my mouse. 

Sample collection script to be run on Arduino Q board - data_collection.py . Onboard script to be run - /home/priyan/uno-q-emulator/app/gesture-recognition/cpp/sketch.ino . Totally 4 gestures are to be captured for data modelling - idle (no movement over x/y/z), back-forth (movement on x), up-down (movement on z which is enabled by holding left mouse button) and circle (movement on x and y). We capture these model as CSV files and upload to online AI model synthesizer. After downloading the AI model for gesture recognition, we load the AI model in UNO Q board to detect gestures via main.py .



I strictly want you to assist me in coding myself, so no code changes must be performed by you. We will containerise the emulated board and create appropriate make targets to complete exercise 3.