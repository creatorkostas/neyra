"""Check installed Piper native code and phoneme data without downloading a voice."""
from piper import PiperVoice
from piper.phonemize_espeak import EspeakPhonemizer

assert callable(PiperVoice.load)
assert callable(PiperVoice.synthesize)
assert EspeakPhonemizer().phonemize("en-us", "Neyra is ready.")
print("Piper native phonemizer and voice APIs passed.")
