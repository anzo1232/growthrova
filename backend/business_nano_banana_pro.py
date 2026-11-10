"""Nano Banana Pro boundary. No credentials, retries, references or paid defaults."""
import base64

MODEL = 'gemini-3-pro-image'
ENDPOINT = 'https://generativelanguage.googleapis.com/v1/models/gemini-3-pro-image:generateContent'
FRAMES = {'square_2k':'1:1', 'portrait_2k':'3:4', 'landscape_2k':'4:3'}
# Old saved requests use a pixel-shaped frame field. Preserve them as aspect choices.
LEGACY_FRAMES = {'1024x1024':'1:1', '1024x1536':'2:3', '1536x1024':'3:2'}


def request_body(prompt, frame):
    ratio = FRAMES.get(frame) or LEGACY_FRAMES.get(frame)
    if not ratio:
        raise ValueError('Unsupported Pro frame')
    return {'contents':[{'role':'user', 'parts':[{'text':prompt}]}],
            'generationConfig':{'candidateCount':1, 'maxOutputTokens':8192,
                'responseModalities':['IMAGE'],
                'imageConfig':{'aspectRatio':ratio, 'imageSize':'2K'}}}


def encoded_image(envelope):
    candidates = envelope.get('candidates') if isinstance(envelope, dict) else None
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError('Expected one completed Google candidate')
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get('finishReason') != 'STOP':
        raise ValueError('Google image did not finish')
    content = candidate.get('content')
    parts = content.get('parts') if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ValueError('Missing Google image parts')
    images = []
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError('Invalid Google image part')
        if part.get('thought') is True:
            continue
        if 'inlineData' in part:
            image = part['inlineData']
            if not isinstance(image, dict) or image.get('mimeType') not in ('image/png', 'image/jpeg'):
                raise ValueError('Expected inline PNG or JPEG')
            images.append(image.get('data'))
        if 'fileData' in part:
            raise ValueError('External image URLs are not accepted')
    if len(images) != 1 or not isinstance(images[0], str):
        raise ValueError('Expected exactly one inline image')
    return images[0]


def validate_dimensions(size, payload):
    width, height = size
    ratio = payload['generationConfig']['imageConfig']['aspectRatio']
    a, b = map(int, ratio.split(':'))
    if (min(width,height) < 1024 or max(width,height) > 4096
            or not 3000000 <= width*height <= 5000000
            or abs((width/height)/(a/b)-1) > 0.02):
        raise ValueError('Image does not match requested 2K frame')
