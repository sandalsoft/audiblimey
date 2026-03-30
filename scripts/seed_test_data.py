#!/usr/bin/env python3
"""Seed test data into audiblimey PostgreSQL database."""

import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "audiblimey",
    "user": "audiblimey",
    "password": "audiblimey_dev",
}


def seed(cur):
    """Insert sample data for testing."""
    
    # --- Authors ---
    cur.execute("""
        INSERT INTO authors (asin, name) VALUES
        ('B000AP9A6K', 'Brandon Sanderson'),
        ('B001H6UJJ8', 'Andy Weir'),
        ('B000AQ0AWU', 'Neil Gaiman')
        ON CONFLICT (asin) DO NOTHING
        RETURNING id;
    """)
    
    # --- Narrators ---
    cur.execute("""
        INSERT INTO narrators (asin, name) VALUES
        ('B0036NJN26', 'Michael Kramer'),
        ('B004LYWJDS', 'R.C. Bray'),
        ('B0036NTQJQ', 'Neil Gaiman')
        ON CONFLICT (asin) DO NOTHING
        RETURNING id;
    """)
    
    # --- Series ---
    cur.execute("""
        INSERT INTO series (asin, title, description) VALUES
        ('B006K1RP1A', 'The Stormlight Archive', 'Epic fantasy series by Brandon Sanderson'),
        ('B0182PWMKY', 'Mistborn', 'Fantasy series set on Scadrial')
        ON CONFLICT (asin) DO NOTHING
        RETURNING id;
    """)
    
    # --- Categories ---
    cur.execute("""
        INSERT INTO categories (audible_category_id, name, level, full_path) VALUES
        ('18574426011', 'Science Fiction & Fantasy', 0, 'Science Fiction & Fantasy'),
        ('18574432011', 'Epic Fantasy', 1, 'Science Fiction & Fantasy > Epic Fantasy'),
        ('18574449011', 'Hard Science Fiction', 1, 'Science Fiction & Fantasy > Hard Science Fiction')
        ON CONFLICT DO NOTHING
        RETURNING id;
    """)
    
    # --- Books ---
    cur.execute("""
        INSERT INTO books (asin, title, subtitle, runtime_length_min, language, merchandising_summary) VALUES
        ('B003ZWFO7E', 'The Way of Kings', 'The Stormlight Archive, Book 1', 2718, 'english',
         'Epic fantasy at its finest. Brandon Sanderson delivers a massive, immersive tale.'),
        ('B00IRUKPQ6', 'The Martian', NULL, 641, 'english',
         'A stranded astronaut must survive alone on Mars with only his ingenuity.'),
        ('B0036N7MUO', 'American Gods', 'The Tenth Anniversary Edition', 1225, 'english',
         'A recently released ex-convict named Shadow meets a mysterious man who calls himself Wednesday.')
        ON CONFLICT (asin) DO NOTHING
        RETURNING id;
    """)
    
    # Get IDs for relationships
    cur.execute("SELECT id FROM books WHERE asin = 'B003ZWFO7E'")
    way_of_kings_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM books WHERE asin = 'B00IRUKPQ6'")
    martian_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM books WHERE asin = 'B0036N7MUO'")
    american_gods_id = cur.fetchone()[0]
    
    cur.execute("SELECT id FROM authors WHERE asin = 'B000AP9A6K'")
    sanderson_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM authors WHERE asin = 'B001H6UJJ8'")
    weir_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM authors WHERE asin = 'B000AQ0AWU'")
    gaiman_id = cur.fetchone()[0]
    
    cur.execute("SELECT id FROM narrators WHERE asin = 'B0036NJN26'")
    kramer_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM narrators WHERE asin = 'B004LYWJDS'")
    bray_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM narrators WHERE asin = 'B0036NTQJQ'")
    gaiman_narrator_id = cur.fetchone()[0]
    
    cur.execute("SELECT id FROM series WHERE asin = 'B006K1RP1A'")
    stormlight_id = cur.fetchone()[0]
    
    cur.execute("SELECT id FROM categories WHERE audible_category_id = '18574432011'")
    epic_fantasy_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM categories WHERE audible_category_id = '18574449011'")
    hard_scifi_id = cur.fetchone()[0]
    
    # --- Relationships ---
    cur.execute("""
        INSERT INTO book_authors (book_id, author_id, role) VALUES
        (%s, %s, 'author'),
        (%s, %s, 'author'),
        (%s, %s, 'author')
        ON CONFLICT DO NOTHING;
    """, (way_of_kings_id, sanderson_id,
          martian_id, weir_id,
          american_gods_id, gaiman_id))
    
    cur.execute("""
        INSERT INTO book_narrators (book_id, narrator_id) VALUES
        (%s, %s), (%s, %s), (%s, %s)
        ON CONFLICT DO NOTHING;
    """, (way_of_kings_id, kramer_id,
          martian_id, bray_id,
          american_gods_id, gaiman_narrator_id))
    
    cur.execute("""
        INSERT INTO book_series (book_id, series_id, sequence, sequence_display) VALUES
        (%s, %s, 1.0, '1')
        ON CONFLICT DO NOTHING;
    """, (way_of_kings_id, stormlight_id))
    
    cur.execute("""
        INSERT INTO book_categories (book_id, category_id) VALUES
        (%s, %s), (%s, %s)
        ON CONFLICT DO NOTHING;
    """, (way_of_kings_id, epic_fantasy_id,
          martian_id, hard_scifi_id))
    
    # --- User library ---
    cur.execute("""
        INSERT INTO user_libraries (user_id, book_id, purchase_date, percent_complete, is_finished, user_rating) VALUES
        (1, %s, '2023-01-15', 100.00, TRUE, 5.0),
        (1, %s, '2023-03-20', 100.00, TRUE, 4.5),
        (1, %s, '2023-06-10', 45.00, FALSE, NULL)
        ON CONFLICT DO NOTHING;
    """, (way_of_kings_id, martian_id, american_gods_id))
    
    # --- Goodreads sample ---
    cur.execute("""
        INSERT INTO goodreads_books (goodreads_book_id, title, author, isbn13, my_rating, average_rating, bookshelves, exclusive_shelf, date_read) VALUES
        ('7235533', 'The Way of Kings', 'Brandon Sanderson', '9780765365279', 5, 4.64, 'favorites, fantasy, epic', 'read', '2023-01-20'),
        ('18007564', 'The Martian', 'Andy Weir', '9780553418026', 4, 4.40, 'sci-fi, favorites', 'read', '2023-03-25'),
        ('30165203', 'A Book I Quit', 'Some Author', '9780000000001', 1, 3.20, 'abandoned, dnf', 'read', '2023-02-10')
        ON CONFLICT DO NOTHING;
    """)
    
    print("Seed data inserted successfully!")
    print("  3 books, 3 authors, 3 narrators, 2 series, 3 categories")
    print("  3 user library entries, 3 goodreads books")


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    
    seed(cur)
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
