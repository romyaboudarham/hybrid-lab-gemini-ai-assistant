# Google Gemini-Powered Voice Assistant 
# Raspberry Pi 5
# 
# Reference code from TechMakerAI on YouTube
#  

from datetime import date
from io import BytesIO
import threading
import queue
import time
import os

# turn off the welcome message from pygame package
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

import google.generativeai as genai
from vertexai.generative_models import GenerativeModel
from gtts import gTTS
 
from pygame import mixer 
import speech_recognition as sr

import sounddevice 

# Hybrid Lab Assistant AI Setup
# Contextual information about the Hybrid Lab
hybrid_lab_context = """
You are the Hybrid Lab Assistant. Go to this website to answer my quesitons "https://portal.cca.edu/learning/shops/hybrid-lab/"
"""

# Raspberry Pi 5 GPIO pins
import gpiod

# Hookswitch
HOOK_SWITCH_PIN = 26
# Open the GPIO chip (GPIO chip 0 is the default on Raspberry Pi)
chip = gpiod.Chip('gpiochip0')
hook_line = chip.get_line(HOOK_SWITCH_PIN)
# set hook switch as input
hook_line.request(consumer="hookswitch", type=gpiod.LINE_REQ_DIR_IN)

import atexit
 # Cleanup: Close the GPIO chip when done
def cleanup_gpio():
    hook_line.release()

atexit.register(cleanup_gpio)

# Phone Keypad
ROWS = [4, 17, 27, 22]
COLS = [5, 6, 13]
KEYS = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#']
]
# Set GPIO lines as input for ROWS
for row in ROWS:
    line = chip.get_line(row)
    line.request(consumer="hookswitch", type=gpiod.LINE_REQ_DIR_IN)

# Set GPIO lines as output for COLS
for col in COLS:
    line = chip.get_line(col)
    line.request(consumer="hookswitch", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
    
# Define key handlers
def handle_key_1(): 
    print("You pressed 1")
    speak_text("What inventory questions do you have?")
def handle_key_2(): print("You pressed 2")
def handle_invalid(): print("Invalid key")

# Dictionary for key actions
key_actions = {
    '1': handle_key_1,
    '2': handle_key_2,
}

# Perform action based on key press
def perform_action(key):
    action = key_actions.get(key, handle_invalid)
    action()
    
def read_keypad():
    for col_index, col in enumerate(COLS):
        # Set current column low
        col_line = chip.get_line(col)
        col_line.set_value(0)
        
        for row_index, row in enumerate(ROWS):
            row_line = chip.get_line(row)
            if row_line.get_value() == 1:
                time.sleep(0.1)
                # Reset the column
                col_line.set_value(1)
                return KEYS[row_index][col_index]
        
        # Reset the column
        col_line.set_value(1)
    
    return None

mixer.pre_init(frequency=24000, buffer=2048) 
mixer.init()

# add your Google Gemini API key here
my_api_key = "AIzaSyDCHDE2Mt02UKSnbsuQihjQZgc7caMugbY"

if len(my_api_key) < 5:
    print(f"Please add your Google Gemini API key in the program. \n " )
    quit() 

# set Google Gemini API key as a system environment variable or add it here
genai.configure(api_key= my_api_key)

# model of Google Gemini API
model = genai.GenerativeModel('gemini-2.0-flash',
    generation_config=genai.GenerationConfig(
        candidate_count=1,
        top_p = 0.95,
        top_k = 64,
        max_output_tokens=60, # 100 tokens correspond to roughly 60-80 words.
        temperature = 0.9,
    ))

# Start a chat session with context
chat = model.start_chat(
    context="You are the Hybrid Lab Assistant. Answer based on https://portal.cca.edu/learning/shops/hybrid-lab/."
)


today = str(date.today())

# Initialize the counters  
numtext = 0 
numtts = 0 
numaudio = 0

# thread 1 for text generation 
def chatfun(request, text_queue, llm_done, stop_event):
    global numtext, chat

    response = chat.send_message(request, stream=True)

    shortstring = '' 
    ctext = ''
    
    for chunk in response:
        try:
            if chunk.candidates[0].content.parts:
                ctext = chunk.candidates[0].content.parts[0].text
                ctext = ctext.replace("*", "")
                
                if len(shortstring) > 10 or len(ctext) > 10:
                    shortstring += ctext
                    text_queue.put(shortstring)
                    print(shortstring, end='')
                    shortstring = ''
                    ctext = ''
                    numtext += 1
                else:
                    shortstring += ctext
                    ctext = ''
        except Exception as e:
            continue  

    if len(ctext) > 0: 
        shortstring += ctext
    if len(shortstring) > 0: 
        print(shortstring, end='') 
        text_queue.put(shortstring)
        numtext += 1
   
    if numtext > 0: 
        append2log(f"AI: {response.candidates[0].content.parts[0].text} \n")
    else:
        llm_done.set()
        stop_event.set()

    llm_done.set()

    
# convert "text" to audio file and play back 
def speak_text(text):
    global slang
           
    mp3file = BytesIO()
    tts = gTTS(text, lang = "en", tld = 'us') 
    tts.write_to_fp(mp3file)

    mp3file.seek(0)
    print("AI: ", text)
    
    try:
        mixer.music.load(mp3file, "mp3")
        mixer.music.play()

        while mixer.music.get_busy():
            time.sleep(0.2)   

    except KeyboardInterrupt:
        mixer.music.stop()
        mp3file = None

    mp3file = None
  
# thread 2 for tts    
def text2speech(text_queue, tts_done, llm_done, audio_queue, stop_event):

    global numtext, numtts
        
    time.sleep(1.0)  
    
    while not stop_event.is_set():  # Keep running until stop_event is set
  
        if not text_queue.empty():

            text = text_queue.get(timeout = 1)  # Wait for 1 second for an item
             
            if len(text) > 0:
                # print(text)
                try:
                    mp3file1 = BytesIO()
                    tts = gTTS(text, lang = "en", tld = 'us') 
                    tts.write_to_fp(mp3file1)
                except Exception as e:
                    continue
                
                audio_queue.put(mp3file1)
                numtts += 1  
                text_queue.task_done()
                
        #print("\n numtts, numtext : ", numtts , numtext)
        
        if llm_done.is_set() and numtts == numtext:             
            #time.sleep(0.3) 
            tts_done.set()
            mp3file1 = None
            #print("\n break from the text queue" )

            break
            


# thread 3 for audio playback 
def play_audio(audio_queue,tts_done, stop_event):
 
    global numtts, numaudio
        
    #print("start play_audio()")
    while not stop_event.is_set():  # Keep running until stop_event is set

        mp3audio1 = BytesIO() 
        mp3audio1 = audio_queue.get()  
        mp3audio1.seek(0)          
        
        mixer.music.load(mp3audio1, "mp3")
        mixer.music.play()

        #print("Numaudio: ", numaudio )  

        while mixer.music.get_busy():
            time.sleep(0.2) 
        
        numaudio += 1 
        audio_queue.task_done()
        
        #print("\n numtts, numaudio : ", numtts , numaudio)
 
        if tts_done.is_set() and numtts  == numaudio: 
            mp3audio1 = None
            #print("\n no more audio/text data, breaking from audio thread")
            break  # Exit loop      
 
# save conversation to a log file 
def append2log(text):
    global today
    fname = 'chatlog-' + today + '.txt'
    with open(fname, "a", encoding='utf-8') as f:
        f.write(text + "\n")
        f.close 
      
# define default language to work with the AI model 
slang = "en-EN"

sleep = True  

def keypad_listener():
    while sleep:
        key = read_keypad()
        if key:
            print(f"Key Pressed: {key}")
            perform_action(key)
            time.sleep(0.3)  # Debounce

def hookswitch_listener():
    global sleep
    was_lifted = False  # Track previous phone state

    while True:
        isPhoneLifted = hook_line.get_value() == 0

        if isPhoneLifted and not was_lifted:
            print("Phone OFF hook")
            sleep = False  # Stay awake
            speak_text("Hello! Welcome to the Hybrid Lab. How may I help you?")

        elif not isPhoneLifted and was_lifted:
            print("Phone ON hook")
            sleep = True  # Stop listening

        was_lifted = isPhoneLifted

def main():
    global today, slang, numtext, numtts, numaudio, sleep

    rec = sr.Recognizer()
    mic = sr.Microphone()
    rec.dynamic_energy_threshold = False
    rec.energy_threshold = 400   

    chat = model.start_chat(context="You are the Hybrid Lab Assistant. Answer based on https://portal.cca.edu/learning/shops/hybrid-lab/.")

    append2log(f"_"*40)
    today = str(date.today())  

    while True:
        if sleep:
            print("Sleeping...")
            continue

        with mic as source:            
            rec.adjust_for_ambient_noise(source, duration=0.5)
            try: 
                print("Listening...")
                audio = rec.listen(source, timeout=10)
                text = rec.recognize_google(audio, language=slang)
                
                if len(text) == 0:
                    continue  

                print(f"You: {text}")
                request = text.lower()

                if "that's all" in request:
                    append2log(f"You: {request}\n")
                    speak_text("Bye now")
                    append2log(f"AI: Bye now.\n")
                    continue

                append2log(f"You: {request}\n")

                text_queue = queue.Queue()
                audio_queue = queue.Queue()
                llm_done = threading.Event()                
                tts_done = threading.Event() 
                stop_event = threading.Event()                

                llm_thread = threading.Thread(target=chatfun, args=(request, text_queue, llm_done, stop_event,))
                tts_thread = threading.Thread(target=text2speech, args=(text_queue, tts_done, llm_done, audio_queue, stop_event,))
                play_thread = threading.Thread(target=play_audio, args=(audio_queue, tts_done, stop_event,))

                llm_thread.start()
                tts_thread.start()
                play_thread.start()

                llm_done.wait()
                llm_thread.join() 

                tts_done.wait()
                audio_queue.join()

                stop_event.set()  
                tts_thread.join()
                play_thread.join()
                print('\n')

            except Exception as e:
                continue 
