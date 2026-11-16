"""Call the HairDemo Voice Agent with text and save its spoken reply.

Setup: python3 -m pip install -r requirements.txt
Set AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET in the .env file
beside this script, or in the environment. Existing environment variables take precedence.
The application needs the Foundry Agent Consumer role on the HairDemo project.
No Azure CLI is required.
Run: python3 call_voice_agent.py
     python3 call_voice_agent.py "Introduce yourself briefly." --output reply.wav
     python3 call_voice_agent.py "Set the AC to 26 degrees." --simulate-tools --output ac-test.wav
     python3 call_voice_agent.py --mic --simulate-tools --output conversation.wav

Text mode waits for the configured welcome before sending the text.
--mic streams the local microphone and plays replies until Ctrl+C; use headphones.
It requires local audio devices and PortAudio (Linux: install libportaudio2).
The microphone belongs to the machine running Python, not a remote VS Code client.
--output saves the agent's audio, not the microphone recording.
This example never controls real devices.
--simulate-tools simulates all household functions defined in voice_agent.yaml.
Simulation state is local to this run; manuals are unavailable unless implemented.
"""

import argparse
import asyncio
import base64
import json
import os
import threading
import uuid
import wave
from pathlib import Path

from azure.identity import ClientSecretCredential
from dotenv import load_dotenv
from websockets.asyncio.client import connect

from simulated_tools import ToolSimulator


ENDPOINT = "wss://hairdemo.services.ai.azure.com/api/projects/HairDemo"
AGENT = "haier-home-flash"


async def handle_tools(
    ws, response: dict, simulator: ToolSimulator | None = None
) -> bool:
    calls = [
        item for item in response.get("output", [])
        if item["type"] == "function_call"
    ]
    if not calls:
        return False
    if simulator is None:
        raise RuntimeError(
            "This example does not execute function tools. "
            "Use --simulate-tools to simulate household functions."
        )
    for call in calls:
        try:
            arguments = json.loads(call["arguments"])
            result = simulator.execute(call["name"], arguments)
        except ValueError as error:
            result = {"success": False, "simulated": True, "error": str(error)}
        print(f"SIMULATED TOOL {call['name']} (no real device change):",
              json.dumps(result, ensure_ascii=False))
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": json.dumps(result),
            },
        }))
    await ws.send(json.dumps({"type": "response.create"}))
    return True


async def microphone_session(
    ws, output: str, simulator: ToolSimulator | None = None
) -> None:
    try:
        import sounddevice as sd
    except ImportError as error:
        raise RuntimeError("Microphone mode requires: pip install -r requirements.txt") from error
    except OSError as error:
        raise RuntimeError(
            "PortAudio is unavailable. On Linux, install libportaudio2. "
            "Microphone mode also requires local microphone and speaker devices."
        ) from error

    loop = asyncio.get_running_loop()
    captured = asyncio.Queue(maxsize=100)
    playback = bytearray()
    lock = threading.Lock()
    audio_error = loop.create_future()
    ready = asyncio.Event()

    def enqueue(data: bytes, status: str) -> None:
        if audio_error.done():
            return
        if status:
            audio_error.set_exception(RuntimeError(f"Audio device error: {status}"))
            return
        if not ready.is_set():
            return
        try:
            captured.put_nowait(data)
        except asyncio.QueueFull:
            audio_error.set_exception(RuntimeError("Microphone upload cannot keep up."))

    def callback(indata, outdata, frames, timing, status) -> None:
        loop.call_soon_threadsafe(enqueue, bytes(indata), str(status) if status else "")
        with lock:
            size = min(len(outdata), len(playback))
            outdata[:] = bytes(playback[:size]) + bytes(len(outdata) - size)
            del playback[:size]

    async def upload() -> None:
        await ready.wait()
        while True:
            data = await captured.get()
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(data).decode("ascii"),
            }))

    async def monitor_audio() -> None:
        await audio_error

    async def receive(recording) -> None:
        active_response = ""
        interrupted_response = ""
        while True:
            event = json.loads(await ws.recv())
            kind = event["type"]
            if kind == "error":
                raise RuntimeError(json.dumps(event["error"], ensure_ascii=False))
            if kind in ("session.created", "session.updated") and not ready.is_set():
                ready.set()
                print("Microphone ready. Speak naturally; press Ctrl+C to stop.")
            elif kind == "response.created":
                active_response = event["response"]["id"]
            elif kind == "input_audio_buffer.speech_started":
                interrupted_response = active_response
                with lock:
                    playback.clear()
            elif kind == "conversation.item.input_audio_transcription.completed":
                print("You:", event["transcript"])
            elif kind == "conversation.item.input_audio_transcription.failed":
                raise RuntimeError(json.dumps(event["error"], ensure_ascii=False))
            elif kind == "response.output_audio.delta":
                if interrupted_response and event.get("response_id") == interrupted_response:
                    continue
                data = base64.b64decode(event["delta"], validate=True)
                with lock:
                    if len(playback) + len(data) > 24000 * 2 * 60:
                        raise RuntimeError("Speaker playback is more than 60 seconds behind.")
                    playback.extend(data)
                recording.writeframesraw(data)
            elif kind == "response.output_audio_transcript.done":
                print("Agent:", event["transcript"])
            elif kind == "response.done":
                response = event["response"]
                if response["status"] == "cancelled":
                    continue
                if response["status"] != "completed":
                    raise RuntimeError(json.dumps(response, ensure_ascii=False))
                await handle_tools(ws, response, simulator)

    try:
        stream = sd.RawStream(
            samplerate=24000, channels=1, dtype="int16",
            blocksize=480, callback=callback,
        )
    except sd.PortAudioError as error:
        raise RuntimeError(
            "Cannot open the local microphone/speaker at 24 kHz. "
            "Run Python on a computer with audio devices; remote SSH does not forward them."
        ) from error
    with stream, wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(24000)
        print(f"Agent audio will be saved to {output}")
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(upload())
            tasks.create_task(receive(recording))
            tasks.create_task(monitor_audio())


async def main(
    text: str, output: str, mic: bool = False,
    simulate_tools: bool = False,
) -> None:
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    simulator = ToolSimulator(Path(__file__).with_name("voice_agent.yaml")) if simulate_tools else None
    if simulator is not None:
        print("SIMULATION ONLY: household state is local to this run; no real devices or orders.")
    required = ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
    with ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    ) as credential:
        token = credential.get_token("https://ai.azure.com/.default").token

    url = (
        f"{ENDPOINT}/agents/{AGENT}/endpoint/protocols/voice"
        f"?api-version=v1&agent_session_id={uuid.uuid4()}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Foundry-Features": "VoiceAgents=V1Preview",
    }
    audio = bytearray()
    transcript = ""
    sent = False

    async with asyncio.timeout(None if mic else 120):
        print("Connecting to the voice agent...")
        async with connect(
            url, additional_headers=headers, max_size=None, open_timeout=30
        ) as ws:
            print("Connected to the voice agent.")
            if mic:
                await microphone_session(ws, output, simulator)
                return
            while True:
                event = json.loads(await ws.recv())
                kind = event["type"]
                if kind == "error":
                    raise RuntimeError(json.dumps(event["error"], ensure_ascii=False))

                if sent and kind == "response.output_audio.delta":
                    audio.extend(base64.b64decode(event["delta"], validate=True))
                elif sent and kind == "response.output_audio_transcript.done":
                    transcript = event["transcript"]
                elif (sent and kind == "response.function_call_arguments.done"
                      and simulator is None):
                    raise RuntimeError(
                        "This example does not execute function tools. "
                        "Use --simulate-tools to simulate household functions."
                    )
                elif kind == "response.done":
                    response = event["response"]
                    if response["status"] != "completed":
                        raise RuntimeError(json.dumps(response, ensure_ascii=False))
                    if sent:
                        if await handle_tools(ws, response, simulator):
                            audio.clear()
                            transcript = ""
                            continue
                        if not transcript.strip() or not audio:
                            raise RuntimeError("The reply has no transcript or audio.")
                        break

                    # The welcome has finished; request a separate user turn.
                    await ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    }))
                    await ws.send(json.dumps({"type": "response.create"}))
                    sent = True

    # The agent is configured for mono, 24 kHz, signed 16-bit PCM.
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(audio)
    print(transcript)
    print(f"Audio saved to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?")
    parser.add_argument("--output", default="reply.wav")
    parser.add_argument("--mic", action="store_true", help="Use the local microphone and speaker until Ctrl+C.")
    parser.add_argument(
        "--simulate-tools", action="store_true",
        help="Simulate household functions from voice_agent.yaml; never controls real devices.",
    )
    args = parser.parse_args()
    if args.text is not None and not args.text.strip():
        parser.error("text must not be empty")
    if args.mic and args.text is not None:
        parser.error("--mic cannot be combined with a text prompt")
    try:
        asyncio.run(main(
            args.text or "Introduce yourself briefly without tools.",
            args.output, mic=args.mic, simulate_tools=args.simulate_tools,
        ))
    except KeyboardInterrupt:
        print("\nStopped.")
