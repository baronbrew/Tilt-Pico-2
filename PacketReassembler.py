class PacketReassembler:
    def __init__(self, total_packets):
        """
        Initializes the PacketReassembler.

        Args:
            total_packets (int): The total number of packets expected for the
                                 complete message.
        """
        if not isinstance(total_packets, int) or total_packets <= 0:
            raise ValueError("total_packets must be a positive integer.")

        self.total_packets = total_packets
        # Initialize a list to hold the reassembled bytes, filled with None
        self._reassembled_bytes = [None] * self.total_packets
        self._received_packet_count = 0
        self._is_complete = False
        self._decoded_string = None

    def add_packet(self, packet_data, packet_num):
        """
        Adds a single packet to the reassembler.

        Args:
            packet_data (bytes or bytearray): A 12-byte packet's data.
            packet_num (int): The packet number (0-indexed or 1-indexed).

        Returns:
            str: The reassembled string if all packets have been received,
                 otherwise None.
        """
        if self._is_complete:
            print("Info: Reassembly already complete. Call reset() to reassemble a new message.")
            return self._decoded_string

        if not isinstance(packet_data, (bytes, bytearray)) or len(packet_data) != 12:
            print(f"Error: Packet {packet_num} data is not 12 bytes or not bytes/bytearray. Ignoring packet.")
            return None

        if not isinstance(packet_num, int):
            print(f"Error: Invalid packet number type: {type(packet_num)}. Must be an integer. Ignoring packet.")
            return None

        # Adjust packet number to be 0-indexed for list access if it's 1-indexed
        if 0 <= packet_num < self.total_packets:
            idx = packet_num
        elif 1 <= packet_num <= self.total_packets:
            idx = packet_num - 1
        else:
            print(f"Error: Invalid packet number: {packet_num}. Must be within 0 to {self.total_packets-1} or 1 to {self.total_packets}. Ignoring packet.")
            return None

        if self._reassembled_bytes[idx] is None:
            self._reassembled_bytes[idx] = packet_data
            self._received_packet_count += 1
            # print(f"Received packet {packet_num}. Total received: {self._received_packet_count}/{self.total_packets}")
        else:
            print(f"Warning: Duplicate packet number received: {packet_num}. Ignoring.")

        if self._received_packet_count == self.total_packets:
            self._is_complete = True
            try:
                full_bytes = b"".join(self._reassembled_bytes)
                self._decoded_string = full_bytes.decode('utf-8')
                return self._decoded_string
            except UnicodeDecodeError:
                print("Error: Could not decode reassembled bytes to UTF-8 string.")
                self._decoded_string = None # Mark as failed decoding
                return None
        else:
            return None

    def is_complete(self):
        """
        Checks if all packets have been received and the message is reassembled.

        Returns:
            bool: True if complete, False otherwise.
        """
        return self._is_complete

    def get_reassembled_string(self):
        """
        Returns the reassembled string if complete, otherwise None.
        """
        return self._decoded_string

    def reset(self):
        """
        Resets the reassembler to prepare for a new message.
        """
        self._reassembled_bytes = [None] * self.total_packets
        self._received_packet_count = 0
        self._is_complete = False
        self._decoded_string = None
        # print("Reassembler reset.")