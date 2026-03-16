from html.parser import HTMLParser


class ExtractHeadingContent(HTMLParser):
    """Extract content under a specific heading in HTML."""
    def __init__(self, target_heading):
        super().__init__()
        self.target_heading = target_heading.lower().strip()
        self.content_parts = []
        self.collecting = False
        self.found_target = False
        self.target_heading_level = None
        self.current_heading_text = []
        self.in_heading = False
        self.current_heading_tag = None

    def handle_starttag(self, tag, attrs):
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # We're entering a heading tag
            self.in_heading = True
            self.current_heading_tag = tag
            self.current_heading_text = []

            # Only include nested headings (deeper level than target)
            if self.collecting and self.found_target:
                heading_level = int(tag[1])
                if heading_level > self.target_heading_level:
                    # This is a nested heading, include it
                    self._append_tag(tag, attrs)
        elif self.collecting and self.found_target:
            # Only collecting content after we've found the target heading
            self._append_tag(tag, attrs)

    def _append_tag(self, tag, attrs):
        """Helper to properly reconstruct an opening tag with all attributes."""
        if attrs:
            attrs_str = ' '.join([f'{k}="{v}"' for k, v in attrs])
            self.content_parts.append(f'<{tag} {attrs_str}>')
        else:
            self.content_parts.append(f'<{tag}>')

    def handle_endtag(self, tag):
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # End of heading tag - check if text matches
            heading_text = ''.join(self.current_heading_text).strip().lower()
            heading_level = int(tag[1])

            if heading_text == self.target_heading and not self.found_target:
                # Found our target heading!
                self.found_target = True
                self.collecting = True
                self.target_heading_level = heading_level
            elif self.found_target and self.collecting:
                # We're collecting content from target heading
                # Stop if we hit a heading of equal or higher level (lower number = higher level)
                if heading_level <= self.target_heading_level:
                    self.collecting = False
                elif heading_level > self.target_heading_level:
                    # This is a nested heading, include its closing tag
                    self.content_parts.append(f'</{tag}>')

            self.in_heading = False
            self.current_heading_text = []
        elif self.collecting and self.found_target:
            # Only collect closing tags if we've found the target heading
            self.content_parts.append(f'</{tag}>')

    def handle_data(self, data):
        if self.in_heading:
            # Accumulate heading text for comparison
            self.current_heading_text.append(data)
            # Only add to output if we're collecting and this is a nested heading (deeper level)
            if self.collecting and self.found_target and self.current_heading_tag:
                heading_level = int(self.current_heading_tag[1])
                if heading_level > self.target_heading_level:
                    self.content_parts.append(data)
        elif self.collecting:
            # Collecting content under target heading
            self.content_parts.append(data)

    def get_content(self):
        return ''.join(self.content_parts).strip()
