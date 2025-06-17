from ucryptolib import aes
from binascii import a2b_base64
# --- Configuration ---
# AES Key - MUST MATCH THE JAVASCRIPT SIDE EXACTLY!
# Make sure it's 16, 24, or 32 bytes long.
#AES_KEY_BYTES = b'MJUBlkVI59Qx47Rz' # <--- REPLACE WITH YOUR EXACT KEY BYTES
# Paste the Base64-encoded encrypted string from the JavaScript output here
#ENCRYPTED_STRING_BASE64 = "ZBZHwt5D+MQvbhtnx9XsQe77n7hRSoN6EfOY/mAEh3Y=" # <--- REPLACE THIS WITH YOUR ENCRYPTED STRING
# --- PKCS7 Padding Removal ---
def pkcs7_unpad(data):
    """Removes PKCS7 padding from decrypted data."""
    padding_len = data[-1]
    if padding_len == 0 or padding_len > len(data): # Sanity check
        raise ValueError("Invalid PKCS7 padding.")
    # Check if all padding bytes are the same value
    if not all(data[-(i + 1)] == padding_len for i in range(padding_len)):
        raise ValueError("Invalid PKCS7 padding (mismatch).")
    return data[:-padding_len]

# --- AES Decryption ---
def decrypt_aes_cbc(encrypted_base64_string, key_bytes = b'MJUBlkVI59Qx47Rz'):
    """
    Decrypts an AES-CBC Base64-encoded string.
    Expected format: Base64( IV (16 bytes) + Ciphertext )
    """
    try:
        # Convert Base64 string back to bytes
        combined_bytes = a2b_base64(encrypted_base64_string)

        # Extract IV (first 16 bytes)
        iv = combined_bytes[0:16]
        # Extract Ciphertext
        ciphertext = combined_bytes[16:]

        # Initialize AES cipher in CBC mode
        # mode=2 for AES_CBC in ucryptolib
        cipher = aes(key_bytes, 2, iv) # 2 for AES_CBC

        # Decrypt the ciphertext
        decrypted_padded_bytes = cipher.decrypt(ciphertext)

        # Remove PKCS7 padding
        plaintext_bytes = pkcs7_unpad(decrypted_padded_bytes)

        # Decode bytes to string
        return plaintext_bytes.decode('utf-8')

    except Exception as e:
        print(f"Decryption failed: {e}")
        return None