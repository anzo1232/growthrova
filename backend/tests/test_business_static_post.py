"""Real static pixels from saved brand/copy; never publication acceptance."""
import io
import unittest
from PIL import Image
import business_brand_render as render

BRAND = dict(name='Synthetic Workshop', primary_color='#123456',
             secondary_color='#FFFFFF', font_style='modern')


class StaticPostRendererTests(unittest.TestCase):
    def test_native_logo_layer_preserves_transparency_and_every_pixel_outside_logo(self):
        from PIL import ImageChops
        with Image.new('RGBA', (800, 600), (23, 160, 80, 90)) as source, Image.new('RGBA', (200, 100), (255, 60, 20, 255)) as logo:
            pixels, layout = render.compose_static_post(source, BRAND, 'Retained headline', 'Retained CTA',
                logo=logo, frame='original', layout='logo-only')
            self.addCleanup(pixels.close)
            self.assertEqual(pixels.mode, 'RGBA', 'A local logo layer cannot flatten the original transparency')
            self.assertEqual(pixels.size, source.size)
            x, y, w, h = layout['logoBox']
            difference = ImageChops.difference(pixels, source)
            self.assertEqual(difference.getbbox(), (x,y,x+w,y+h))
            self.assertEqual(source.getpixel((0,0)), (23,160,80,90))
            self.assertEqual(pixels.getpixel((x+w//2,y+h//2)), (255,60,20,255))

    def test_logo_header_preserves_a_long_saved_brand_name_readably(self):
        source=Image.new('RGB',(400,200))
        logo=Image.new('RGBA',(200,100),(255,60,20,255))
        brand=dict(BRAND,name='Northside Bicycle Service Workshop')
        pixels,layout=render.compose_static_post(source,brand,
            'Bicycle servicing at our workshop.','Explore the workshop',logo=logo)
        self.assertGreaterEqual(layout['textBlocks'][0]['fontSize'],48)
        self.assertLessEqual(layout['textBlocks'][0]['bottom'],150)
        pixels.close();source.close();logo.close()

    def test_explicit_logo_keeps_alpha_aspect_and_source_pixels(self):
        source = Image.new('RGB', (400, 200), (23, 160, 80))
        logo = Image.new('RGBA', (200, 100), (255, 60, 20, 0))
        for x in range(100):
            for y in range(100): logo.putpixel((x, y), (255, 60, 20, 255))
        pixels, layout = render.compose_static_post(source, BRAND,
            'Bicycle servicing at our workshop.', 'Explore the workshop', logo=logo)
        x, y, w, h = layout['logoBox']
        self.assertEqual(w/h, 2)
        self.assertEqual(pixels.getpixel((x+w//4, y+h//2)), (255, 60, 20))
        self.assertEqual(pixels.getpixel((x+3*w//4, y+h//2)), (18, 52, 86))
        self.assertEqual(pixels.getpixel((540, 400)), (23, 160, 80))
        self.assertTrue(layout['logoIncluded'])
        self.assertEqual(logo.size, (200, 100))
        pixels.close(); logo.close(); source.close()

    def test_exact_complete_words_and_contained_source_pixels(self):
        source = Image.new('RGB', (400, 200), (23, 160, 80))
        pixels, layout = render.compose_static_post(source, BRAND,
            'Make room for your next project.', 'Explore the workshop')
        self.assertEqual(pixels.size, (1080, 1350))
        self.assertEqual(pixels.getpixel((540, 400))[:3], (23, 160, 80))
        self.assertEqual(source.size, (400, 200))
        self.assertEqual(layout['copy'], 'Make room for your next project.')
        self.assertEqual(layout['callToAction'], 'Explore the workshop')
        self.assertEqual(layout['photoBox'][2] / layout['photoBox'][3], 2)
        for box in layout['textBlocks']:
            self.assertGreaterEqual(box['fontSize'], 48)
            self.assertLessEqual(box['bottom'], box['limit'])
        self.assertFalse(layout['logoIncluded'])

    def test_complete_two_line_cta_fits_without_shrinking_below_mobile_minimum(self):
        source = Image.new('RGB', (400, 200))
        cta = 'Discuss bicycle servicing with our workshop team'
        pixels, layout = render.compose_static_post(source, BRAND, 'Bicycle servicing at our workshop.', cta)
        self.assertEqual(layout['callToAction'], cta)
        self.assertGreaterEqual(layout['textBlocks'][-1]['fontSize'], 48)
        self.assertLessEqual(layout['textBlocks'][-1]['bottom'], 1320)
        pixels.close()

    def test_story_keeps_complete_logo_photo_and_mobile_text_inside_safe_area(self):
        with Image.new('RGB', (400, 200), (23, 160, 80)) as source, Image.new('RGBA', (200, 100), (255, 60, 20, 255)) as logo:
            pixels, layout = render.compose_static_post(source, BRAND,
                'Make room for your next project.', 'Explore the workshop', logo=logo, frame='story')
            self.addCleanup(pixels.close)
            self.assertEqual(pixels.size, (1080, 1920))
            for field in ('photoBox', 'logoBox'):
                x, y, w, h = layout[field]
                self.assertGreaterEqual(x, 64)
                self.assertLessEqual(x+w, 1016)
                self.assertGreaterEqual(y, 250)
                self.assertLessEqual(y+h, 1580)
                self.assertEqual(w/h, 2, 'Whole original aspect ratio must survive')
            x, y, w, h = layout['logoBox']
            self.assertEqual(pixels.getpixel((x+w//2, y+h//2)), (255, 60, 20))
            self.assertEqual(layout['copy'], 'Make room for your next project.')
            self.assertEqual(layout['callToAction'], 'Explore the workshop')
            for block in layout['textBlocks']:
                self.assertGreaterEqual(block['fontSize'], 48)
                self.assertLessEqual(block['bottom'], block['limit'])
                self.assertLessEqual(block['limit'], 1580)

    def test_overflow_and_unreadable_palette_are_held_without_truncation(self):
        source = Image.new('RGB', (400, 200))
        for brand, copy, cta in [(BRAND, 'Long copy. '*300, 'Read more'),
                (BRAND, '', 'Read more'), (BRAND, 'A complete sentence.', ''),
                (dict(BRAND, secondary_color='#123456'), 'A complete sentence.', 'Read more'),
                (BRAND, 'x'*200, 'Read more')]:
            with self.subTest(copy=copy[:30]), self.assertRaises(render.BrandRenderError):
                render.compose_static_post(source, brand, copy, cta)
