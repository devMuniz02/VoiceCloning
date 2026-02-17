import gradio as gr
import os
import whisper
import soundfile as sf
import torch
import numpy as np
from qwen_tts import Qwen3TTSModel
import subprocess
import base64
import gc

# Load models on demand
whisper_model = whisper.load_model("base")
current_model = None
current_model_name = "1.7B"

def load_model(name):
    if name == "0.6B":
        return Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    else:
        return Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base")

# Load default model
current_model = load_model("1.7B")

def set_model(model_name):
    global current_model, current_model_name
    if model_name != current_model_name:
        del current_model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        current_model = load_model(model_name)
        current_model_name = model_name

def get_voices():
    voices_dir = "voices"
    if os.path.exists(voices_dir):
        return [d for d in os.listdir(voices_dir) if os.path.isdir(os.path.join(voices_dir, d))]
    return []

def add_voice(name, url, start, end):
    if not name or not url or not start or not end:
        return "Please fill all fields for new voice."
    
    voice_dir = f"voices/{name}"
    os.makedirs(voice_dir, exist_ok=True)
    
    ref_audio = f"{voice_dir}/{name}_source.wav"
    ref_text_file = f"{voice_dir}/{name}_reference_text.txt"
    
    if not os.path.exists(ref_audio):
        print("Downloading audio...")
        command = (
            f'yt-dlp -x --audio-format wav '
            f'--download-sections "*{start}-{end}" '
            f'-o "{voice_dir}/{name}_source.%(ext)s" {url}'
        )
        subprocess.run(command, shell=True)
    
    if not os.path.exists(ref_text_file):
        print("Transcribing...")
        result = whisper_model.transcribe(ref_audio)
        reference_text = result['text'].strip()
        with open(ref_text_file, 'w', encoding='utf-8') as f:
            f.write(reference_text)
    
    return f"Voice '{name}' added successfully."

def delete_voice(name):
    if not name:
        return "Please select a voice to delete."
    
    voice_dir = f"voices/{name}"
    if os.path.exists(voice_dir):
        import shutil
        shutil.rmtree(voice_dir)
        # Also delete generations
        gen_dir = f"generations/{name}"
        if os.path.exists(gen_dir):
            shutil.rmtree(gen_dir)
        return f"Voice '{name}' and its generations deleted."
    return f"Voice '{name}' not found."

def generate_audio(voice, text, language):
    if not voice or not text:
        return "Please select a voice and enter text."
    
    ref_audio = f"voices/{voice}/{voice}_source.wav"
    ref_text_file = f"voices/{voice}/{voice}_reference_text.txt"
    
    if not os.path.exists(ref_audio) or not os.path.exists(ref_text_file):
        return "Reference audio or text missing for this voice."
    
    with open(ref_text_file, 'r', encoding='utf-8') as f:
        reference_text = f.read().strip()
    
    generations_dir = f"generations/{voice}"
    os.makedirs(generations_dir, exist_ok=True)
    
    # Check if already generated
    for file in os.listdir(generations_dir):
        if file.endswith('.txt'):
            txt_path = os.path.join(generations_dir, file)
            with open(txt_path, 'r', encoding='utf-8') as f:
                if f.read().strip() == text:
                    return "Audio already generated for this text."
    
    print("Generating...")
    wavs, sr = current_model.generate_voice_clone(
        ref_audio=ref_audio,
        ref_text=reference_text,
        text=text,
        language=language
    )
    
    wav = wavs[0]
    if isinstance(wav, torch.Tensor):
        wav = wav.detach().cpu().numpy()
    wav = wav.squeeze()
    if wav.dtype != np.float32:
        wav = wav.astype(np.float32)
    
    n = 1
    while os.path.exists(os.path.join(generations_dir, f"{n}.wav")):
        n += 1
    
    audio_file = os.path.join(generations_dir, f"{n}.wav")
    text_file = os.path.join(generations_dir, f"{n}.txt")
    
    sf.write(audio_file, wav, sr)
    with open(text_file, 'w', encoding='utf-8') as f:
        f.write(text)
    
    return f"Audio generated and saved for voice '{voice}'."

def get_generations_html():
    html = '<div style="max-width: 800px; margin: 0 auto; font-family: Arial, sans-serif;">'
    html += "<h2 style='text-align: center; color: #333;'>Generated Voices</h2>"
    generations_dir = "generations"
    if os.path.exists(generations_dir):
        for voice in sorted(os.listdir(generations_dir)):
            voice_dir = os.path.join(generations_dir, voice)
            if os.path.isdir(voice_dir):
                html += f"<h3 style='color: #555; border-bottom: 1px solid #ddd; padding-bottom: 5px;'>{voice.title()}</h3>"
                files = sorted([f for f in os.listdir(voice_dir) if f.endswith('.wav')], key=lambda x: int(x.split('.')[0]))
                for file in files:
                    num = file.split('.')[0]
                    txt_file = f"{num}.txt"
                    txt_path = os.path.join(voice_dir, txt_file)
                    wav_path = os.path.join(voice_dir, file)
                    if os.path.exists(txt_path):
                        with open(txt_path, 'r', encoding='utf-8') as f:
                            text = f.read()
                        # Encode audio to base64
                        with open(wav_path, 'rb') as audio_file:
                            encoded = base64.b64encode(audio_file.read()).decode('utf-8')
                        html += f'<div style="display: flex; align-items: center; margin-bottom: 15px; padding: 10px; border: 1px solid #ccc; border-radius: 5px; background-color: #666; color: white;"><audio controls style="margin-right: 15px; flex-shrink: 0;"><source src="data:audio/wav;base64,{encoded}" type="audio/wav"></audio><p style="margin: 0; flex: 1;"><strong>Text:</strong> {text}</p></div>'
    if html == '<div style="max-width: 800px; margin: 0 auto; font-family: Arial, sans-serif;"><h2 style=\'text-align: center; color: #333;\'>Generated Voices</h2>':
        html += "<p style='text-align: center; color: #777;'>No generations yet.</p>"
    html += "</div>"
    return html

def get_generations(voice):
    if voice:
        gen_dir = f"generations/{voice}"
        if os.path.exists(gen_dir):
            files = [f for f in os.listdir(gen_dir) if f.endswith('.wav')]
            return sorted([f.split('.')[0] for f in files], key=int)
    return []

def delete_generation(voice, gen_num):
    if not voice or not gen_num:
        return "Please select a voice and generation to delete."
    
    wav_path = f"generations/{voice}/{gen_num}.wav"
    txt_path = f"generations/{voice}/{gen_num}.txt"
    
    deleted = False
    if os.path.exists(wav_path):
        os.remove(wav_path)
        deleted = True
    if os.path.exists(txt_path):
        os.remove(txt_path)
        deleted = True
    
    if deleted:
        return f"Generation {gen_num} for voice '{voice}' deleted."
    else:
        return f"Generation {gen_num} not found for voice '{voice}'."

def update_voices():
    choices = get_voices()
    return gr.Dropdown(choices=choices), gr.Dropdown(choices=choices), gr.Dropdown(choices=choices)

def update_display():
    return get_generations_html()

with gr.Blocks(title="Voice Clone App") as demo:
    gr.Markdown("# 🎤 Voice Clone App")
    
    with gr.Row():
        gr.HTML('<div style="padding: 10px; border: 1px solid #555; border-radius: 5px; background-color: #333; text-align: center;"><a href="https://github.com/devMuniz02/" target="_blank" style="text-decoration: none; color: white;">🐙 GitHub: devMuniz02</a></div>')
        gr.HTML('<div style="padding: 10px; border: 1px solid #555; border-radius: 5px; background-color: #333; text-align: center;"><a href="https://www.linkedin.com/in/devmuniz" target="_blank" style="text-decoration: none; color: white;">💼 LinkedIn: devmuniz</a></div>')
        gr.HTML('<div style="padding: 10px; border: 1px solid #555; border-radius: 5px; background-color: #333; text-align: center;"><a href="https://huggingface.co/manu02" target="_blank" style="text-decoration: none; color: white;">🤗 Hugging Face: manu02</a></div>')
        gr.HTML('<div style="padding: 10px; border: 1px solid #555; border-radius: 5px; background-color: #333; text-align: center;"><a href="https://devmuniz02.github.io/" target="_blank" style="text-decoration: none; color: white;">🌐 Portfolio: devmuniz02</a></div>')
    
    with gr.Tabs():
        with gr.TabItem("Manage Voices"):
            gr.Markdown("### Select and Delete Voices")
            with gr.Row():
                voice_dropdown = gr.Dropdown(label="Select Voice", choices=get_voices())
                delete_btn = gr.Button("🗑️ Delete Voice", variant="stop")
            delete_output = gr.Textbox(label="Status", interactive=False)
            
            gr.Markdown("### Add New Voice")
            with gr.Row():
                new_name = gr.Textbox(label="Voice Name", placeholder="e.g., spongebob")
                new_url = gr.Textbox(label="YouTube URL", placeholder="https://youtu.be/...") 
            with gr.Row():
                new_start = gr.Textbox(label="Start Time", placeholder="00:00:10")
                new_end = gr.Textbox(label="End Time", placeholder="00:03:10")
            add_btn = gr.Button("➕ Add Voice", variant="primary")
            add_output = gr.Textbox(label="Status", interactive=False)
        
        with gr.TabItem("Generate Audio"):
            gr.Markdown("### Generate New Audio")
            model_dropdown = gr.Dropdown(label="Model", choices=["1.7B", "0.6B"], value="1.7B")
            voice_gen_dropdown = gr.Dropdown(label="Select Voice", choices=get_voices())
            language_dropdown = gr.Dropdown(label="Language", choices=["Chinese", "English", "Japanese", "Korean", "German", "French", "Russian", "Portuguese", "Spanish", "Italian"], value="English")
            gen_text = gr.Textbox(label="Text to Generate", lines=4, placeholder="Enter the text for voice cloning...")
            gen_btn = gr.Button("🎵 Generate Audio", variant="primary")
            gen_output = gr.Textbox(label="Status", interactive=False)
        
        with gr.TabItem("View Generations"):
            gr.Markdown("### All Generated Audios")
            display = gr.HTML(value=get_generations_html())
            refresh_btn = gr.Button("🔄 Refresh")
            
            gr.Markdown("### Delete a Generation")
            with gr.Row():
                voice_del_gen = gr.Dropdown(label="Select Voice", choices=get_voices())
                gen_files = gr.Dropdown(label="Select Generation", choices=[])
            del_gen_btn = gr.Button("🗑️ Delete Generation", variant="stop")
            del_output = gr.Textbox(label="Status", interactive=False)
    
    # Event handlers
    add_btn.click(add_voice, inputs=[new_name, new_url, new_start, new_end], outputs=add_output).then(update_voices, outputs=[voice_dropdown, voice_gen_dropdown, voice_del_gen]).then(update_display, outputs=display)
    delete_btn.click(delete_voice, inputs=voice_dropdown, outputs=delete_output).then(update_voices, outputs=[voice_dropdown, voice_gen_dropdown, voice_del_gen]).then(update_display, outputs=display)
    model_dropdown.change(set_model, inputs=model_dropdown)
    gen_btn.click(generate_audio, inputs=[voice_gen_dropdown, gen_text, language_dropdown], outputs=gen_output).then(update_display, outputs=display)
    refresh_btn.click(update_display, outputs=display)
    voice_del_gen.change(lambda voice: gr.Dropdown(choices=get_generations(voice)), inputs=voice_del_gen, outputs=gen_files)
    del_gen_btn.click(delete_generation, inputs=[voice_del_gen, gen_files], outputs=del_output).then(update_display, outputs=display).then(lambda voice: gr.Dropdown(choices=get_generations(voice)), inputs=voice_del_gen, outputs=gen_files)

if __name__ == "__main__":
    demo.launch()