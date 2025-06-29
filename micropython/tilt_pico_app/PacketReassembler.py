class PacketReassembler:
    def __init__(self):
        """
        Initializes the PacketReassembler.
        Packet length is fixed at 24 bytes.
        Packet number and total packets are provided separately to add_packet.
        This instance enforces 1-indexed packet numbering (packet_num starts from 1).
        """
        self.PACKET_LENGTH = 24

        self.total_packets = -1
        self._reassembled_bytes = None
        self._received_packet_count = 0
        self._is_complete = False
        self._decoded_string = None

    def add_packet(self, packet_data, packet_num, total_packets_arg):
        """
        Adds a single packet to the reassembler.
        This function expects 1-indexed packet numbers (packet_num starts from 1).

        Args:
            packet_data (bytes or bytearray): The 24-byte data payload of the packet.
            packet_num (int): The 1-indexed number of this packet (e.g., 1, 2, 3...).
            total_packets_arg (int): The total number of packets expected for the complete message.

        Returns:
            str: The reassembled string if all packets have been received,
                 otherwise None. Returns None also on error.
        """
        if self._is_complete:
            print("Info: Reassembly already complete. Call reset() to reassemble a new message.")
            return self._decoded_string

        # Validate incoming packet_data
        if not isinstance(packet_data, (bytes, bytearray)) or len(packet_data) != self.PACKET_LENGTH:
            print(f"Error: Incoming packet data is not {self.PACKET_LENGTH} bytes or not bytes/bytearray. Ignoring packet.")
            return None
        if not isinstance(packet_num, int) or not isinstance(total_packets_arg, int):
            print(f"Error: packet_num ({packet_num}) or total_packets_arg ({total_packets_arg}) is not an integer. Ignoring packet.")
            return None

        # Initialize or validate total_packets for the current message
        if self.total_packets == -1: # First packet for this message
            if total_packets_arg <= 0:
                print(f"Error: Initial total_packets_arg value is invalid ({total_packets_arg}). Resetting reassembler.")
                self.reset()
                return None
            self.total_packets = total_packets_arg
            self._reassembled_bytes = [None] * self.total_packets
        elif self.total_packets != total_packets_arg:
            # This indicates a potential new message being sent without a reset, or corrupted total_packets_arg.
            print(f"Warning: Inconsistent total_packets_arg. Expected {self.total_packets}, but received {total_packets_arg}. "
                  "This might indicate a new message without a reset, or corrupted data. Ignoring packet.")
            return None

        # Validate packet_num strictly for 1-indexed and calculate idx
        if 1 <= packet_num <= self.total_packets:
            idx = packet_num - 1 # Convert 1-indexed to 0-indexed array index
        else:
            print(f"Error: Invalid packet number ({packet_num}). Expected 1 to {self.total_packets}. Ignoring packet.")
            return None

        # Add packet data to the buffer if not a duplicate
        if self._reassembled_bytes[idx] is None:
            self._reassembled_bytes[idx] = packet_data
            self._received_packet_count += 1
        else:
            print(f"Warning: Duplicate packet number ({packet_num}) received. Ignoring.")

        # Check for completion
        if self._received_packet_count == self.total_packets:
            self._is_complete = True
            try:
                full_bytes = b"".join(self._reassembled_bytes)
                self._decoded_string = full_bytes.decode('utf-8')
                return self._decoded_string
            except UnicodeDecodeError:
                print("Error: Could not decode reassembled bytes to UTF-8 string.")
                self._decoded_string = None
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
        self.total_packets = -1
        self._reassembled_bytes = None
        self._received_packet_count = 0
        self._is_complete = False
        self._decoded_string = None