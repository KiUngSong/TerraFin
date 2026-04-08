import sec_parser as sp
from sec_parser.semantic_elements import SupplementaryText, TableElement, TextElement, TitleElement, TopSectionTitle

from TerraFin.data.utils.md_to_df import from_md_to_df


def parse_sec_filing(html_content, filing_form="10-Q"):
    """
    Parse SEC filing HTML content into structured markdown format.

    Args:
        html_content (str): Raw HTML content from SEC filing
        filing_form (str): Type of filing ("10-Q", "10-K", etc.)

    Returns:
        str: Parsed content in markdown format
    """
    if "10-Q" in filing_form:
        return _parse_10q(html_content)
    elif "10-K" in filing_form:
        return _parse_10k(html_content)
    else:
        raise ValueError(f"Filing form '{filing_form}' not supported.")


def _parse_10q(html_content):
    """Parse 10-Q filing content."""
    elements = sp.Edgar10QParser().parse(html_content)

    # Filter out the elements
    filtered_content = []

    # Check if the title has been encountered to avoid dummy text
    title_encountered = False
    for element in elements:
        if isinstance(element, TopSectionTitle) or isinstance(element, TitleElement):
            filtered_content.append(f"#### {element.text}" + "\n")
            title_encountered = True

        elif isinstance(element, TextElement) and title_encountered:
            filtered_content.append(element.text + "\n")

        elif isinstance(element, SupplementaryText) and title_encountered:
            filtered_content.append(element.text + "\n")

        elif isinstance(element, TableElement) and title_encountered:
            filtered_content.append(
                # Add a new line after the table
                _modify_to_valid_md_table(element.table_to_markdown()) + "\n"
            )

    parsed_content = "\n".join(filtered_content)

    return parsed_content


def _parse_10k(html_content):
    """Parse 10-K filing content (uses same logic as 10-Q for now)."""
    return _parse_10q(html_content)


def _modify_to_valid_md_table(text):
    """
    Convert SEC table markdown to valid pandas-compatible markdown table.

    Args:
        text (str): Raw markdown table text

    Returns:
        str: Valid markdown table
    """
    texts = text.split("\n")

    # Count the number of columns: "|"
    num_columns = texts[0].count("|")
    column_indicator = "|" + " --- |" * (num_columns - 1)

    # Insert the column indicator
    new_texts = [texts[0], column_indicator]
    for i in range(1, len(texts)):
        new_texts.append(texts[i])
    markdown_txt = "\n".join(new_texts)

    # Modify to pandas dataframe
    table_df = from_md_to_df(markdown_txt)

    def drop_empty_columns(df):
        # Iterate over the columns and drop those where all values are empty strings or spaces
        return df.loc[:, ~(df.apply(lambda col: col.str.strip().eq("")).all())]

    table_df = drop_empty_columns(table_df)
    valid_markdown_txt = table_df.to_markdown(index=False)

    return valid_markdown_txt
